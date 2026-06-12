-- 2026-06-13：清掉多實例同時跑造成的重複動作記錄
-- 同 action + 完全相同 detail 的列，只保留最早一筆
delete from actions_log a
using actions_log b
where a.id > b.id
  and a.action = b.action
  and a.detail = b.detail;
