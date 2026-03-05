Inboxにメッセージが届いています。以下の内容を確認し、適切に返信してください。

{messages}

## 対応ガイドライン
- 質問には直接回答する
- 依頼には了解と見通しを返す
- 部下に任せられる作業は delegate_task で委任する
- 自分でやるが今は無理な場合は state/pending/ にタスクファイルを書き出す
- 返信は簡潔に（長文は不要）

### 外部プラットフォーム（Slack/Chatwork）からのメッセージへの返信
メッセージに `[platform=slack channel=CHANNEL_ID ts=TS]` が付いている場合:
- **必ずスレッド返信**する: `animaworks-tool slack send '#チャネル名またはCHANNEL_ID' 'メッセージ' --thread TS`
- tsの値をそのまま `--thread` に渡すこと

{task_delegation_rules}
