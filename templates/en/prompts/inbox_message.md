You have messages in your inbox. Review the following and reply appropriately.

{messages}

## Response Guidelines
- Answer questions directly
- Reply with acknowledgment and timeline for requests
- Delegate work to subordinates via delegate_task when possible
- If you need to do it yourself but not right now, write a task file to state/pending/
- Keep replies concise (no lengthy responses)

### Replying to External Platform (Slack/Chatwork) Messages
When a message has `[platform=slack channel=CHANNEL_ID ts=TS]` metadata:
- **Always reply in thread**: `animaworks-tool slack send '#channel-or-CHANNEL_ID' 'message' --thread TS`
- Pass the ts value directly to `--thread`

{task_delegation_rules}
