/**
 * 投稿の起動役になる Google Apps Script（シートに付けない独立したプロジェクトとして作る）。
 * シートは「リンクを知っている全員が編集可」なので、シートに付けると GITHUB_TOKEN が見えてしまう。
 *
 * GitHub Actions の定時実行は大きく遅れたり飛ばされたりするため、
 * Google の時刻トリガーで定期的にシートを見て、投稿の予定時刻を過ぎた承認済みの行があれば
 * GitHub の「Threads 投稿」ワークフローを呼び出す。毎週日曜 10時台には下書き作成も呼び出す。
 *
 * 準備：プロジェクトの設定 → スクリプト プロパティに GITHUB_TOKEN と SHEET_ID を登録し、
 *       setupTriggers を1回だけ実行する。
 */
const REPO = 'masaharu0312/threads_auto';
// シートIDは公開リポジトリに載せない（スクリプト プロパティの SHEET_ID に登録する）
const SHEET_ID = PropertiesService.getScriptProperties().getProperty('SHEET_ID');
const SLOTS = { '朝': [8, 0], '昼': [12, 30], '夜': [20, 30] };
const GRACE_MINUTES = 180;        // post.py の GRACE と合わせる
const DONE_STATES = ['投稿済み', '未承認のため見送り', '見送り（時間切れ）'];
const MIN_INTERVAL_MINUTES = 8;   // 投稿処理を続けて呼びすぎないための間隔

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
function hasDuePost_() {
  const values = SpreadsheetApp.openById(SHEET_ID).getSheetByName('投稿').getDataRange().getDisplayValues();
  const head = values[0];
  const c = (name) => head.indexOf(name);
  const now = new Date();
  return values.slice(1).some((r) => {
    if (!r[c('ID')] || DONE_STATES.indexOf(r[c('状態')]) >= 0) return false;
    if (String(r[c('承認')]).toUpperCase() !== 'TRUE') return false;
    // 本文は出たがコメントが途中のもの（コメント中・コメント失敗）は、時間がたっていても続きを付ける
    if (c('投稿ID') >= 0 && r[c('投稿ID')]) return true;
    const slot = SLOTS[r[c('枠')]];
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
  const last = Number(props.getProperty('LAST_POST_DISPATCH') || 0);
  if (Date.now() - last < MIN_INTERVAL_MINUTES * 60000) return;
  if (!hasDuePost_()) return;
  dispatch_('post.yml');
  props.setProperty('LAST_POST_DISPATCH', String(Date.now()));
}

/** 毎週日曜 10時台に呼ばれる：翌週の下書きを作る */
function weeklyGenerate() {
  dispatch_('generate.yml');
}

/** 最初に1回だけ実行する：トリガーを作り直す */
function setupTriggers() {
  ScriptApp.getProjectTriggers().forEach((t) => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('checkAndPost').timeBased().everyMinutes(10).create();
  ScriptApp.newTrigger('weeklyGenerate').timeBased()
    .onWeekDay(ScriptApp.WeekDay.SUNDAY).atHour(10).inTimezone('Asia/Tokyo').create();
}
