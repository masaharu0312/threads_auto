/**
 * 投稿の起動役になる Google Apps Script（シートに付けない独立したプロジェクトとして作る）。
 * シートは「リンクを知っている全員が編集可」なので、シートに付けると GITHUB_TOKEN が見えてしまう。
 *
 * GitHub Actions の定時実行は大きく遅れたり飛ばされたりするため、
 * Google の時刻トリガーで定期的にシートを見て、投稿の予定時刻を過ぎた承認済みの行があれば
 * GitHub の投稿ワークフローを呼び出す。毎週日曜 10時台には下書き作成も呼び出す。
 * どこでもMUSEE と、美容のお仕事案内（BEAUTY_SHEET_ID があるときだけ）の両方を見る。
 *
 * 準備：プロジェクトの設定 → スクリプト プロパティに GITHUB_TOKEN と SHEET_ID
 *       （美容も動かすなら BEAUTY_SHEET_ID）を登録し、setupTriggers を1回だけ実行する。
 */
const REPO = 'masaharu0312/threads_auto';
const GRACE_MINUTES = 180;        // post.py の GRACE と合わせる
const MIN_INTERVAL_MINUTES = 8;   // 投稿処理を続けて呼びすぎないための間隔
// シートIDは公開リポジトリに載せない（スクリプト プロパティに登録する）
// 時刻は各アカウントの common.py の SLOTS と合わせる
const ACCOUNTS = [
  {
    key: 'MUSEE', sheetProp: 'SHEET_ID', post: 'post.yml', generate: 'generate.yml',
    slots: { '朝': [8, 0], '昼': [12, 30], '夜': [20, 30] },
    doneStates: ['投稿済み', '未承認のため見送り', '見送り（時間切れ）'],
  },
  {
    key: 'BEAUTY', sheetProp: 'BEAUTY_SHEET_ID', post: 'beauty-post.yml', generate: 'beauty-generate.yml',
    slots: { '朝': [7, 30], '昼': [12, 30], '夜': [21, 0] },
    doneStates: ['投稿済み', '投稿済み（コメント途中）', '未承認のため見送り', '見送り（時間切れ）'],
  },
];

function sheetId_(account) {
  return PropertiesService.getScriptProperties().getProperty(account.sheetProp);
}

function dispatch_(workflow) {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('スクリプト プロパティに GITHUB_TOKEN がありません');
  const res = UrlFetchApp.fetch(
    'https://api.github.com/repos/' + REPO + '/actions/workflows/' + workflow + '/dispatches', {
      method: 'post',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
      payload: JSON.stringify({ ref: 'main', inputs: {} }),
      muteHttpExceptions: true,
    });
  if (res.getResponseCode() !== 204) {
    throw new Error('GitHub の呼び出しに失敗: ' + res.getResponseCode() + ' ' + res.getContentText());
  }
}

/** 予定時刻を過ぎた承認済みの未投稿があるか（シートの「投稿」タブを見る） */
function hasDuePost_(account) {
  const values = SpreadsheetApp.openById(sheetId_(account)).getSheetByName('投稿').getDataRange().getDisplayValues();
  const head = values[0];
  const c = (name) => head.indexOf(name);
  const now = new Date();
  return values.slice(1).some((r) => {
    if (!r[c('ID')] || account.doneStates.indexOf(r[c('状態')]) >= 0) return false;
    if (String(r[c('承認')]).toUpperCase() !== 'TRUE') return false;
    // 本文は出たがコメントが途中のもの（コメント中・コメント失敗）は、時間がたっていても続きを付ける
    if (c('投稿ID') >= 0 && r[c('投稿ID')]) return true;
    const slot = account.slots[r[c('枠')]];
    const d = String(r[c('日付')]).split(/[-\/]/).map(Number);
    if (!slot || d.length !== 3) return false;
    // 日本時間の予定時刻（UTC に直して比較する）
    const at = new Date(Date.UTC(d[0], d[1] - 1, d[2], slot[0] - 9, slot[1]));
    const late = (now - at) / 60000;
    return late >= 0 && late <= GRACE_MINUTES;
  });
}

/** 10分ごとに呼ばれる：投稿の予定があれば GitHub の投稿処理を動かす */
function checkAndPost() {
  const props = PropertiesService.getScriptProperties();
  const errors = [];
  ACCOUNTS.forEach((account) => {
    if (!sheetId_(account)) return;
    // MUSEE は以前からのキー名のまま
    const lastKey = account.key === 'MUSEE' ? 'LAST_POST_DISPATCH' : 'LAST_POST_DISPATCH_' + account.key;
    const last = Number(props.getProperty(lastKey) || 0);
    if (Date.now() - last < MIN_INTERVAL_MINUTES * 60000) return;
    try {  // 片方が失敗しても、もう片方は動かす
      if (!hasDuePost_(account)) return;
      dispatch_(account.post);
      props.setProperty(lastKey, String(Date.now()));
    } catch (e) {
      errors.push(account.key + ': ' + e.message);
    }
  });
  if (errors.length) throw new Error(errors.join('\n'));
}

/** 毎週日曜 10時台に呼ばれる：翌週の下書きを作る */
function weeklyGenerate() {
  ACCOUNTS.forEach((account) => {
    if (sheetId_(account)) dispatch_(account.generate);
  });
}

/** 最初に1回だけ実行する：トリガーを作り直す */
function setupTriggers() {
  ScriptApp.getProjectTriggers().forEach((t) => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('checkAndPost').timeBased().everyMinutes(10).create();
  ScriptApp.newTrigger('weeklyGenerate').timeBased()
    .onWeekDay(ScriptApp.WeekDay.SUNDAY).atHour(10).inTimezone('Asia/Tokyo').create();
}
