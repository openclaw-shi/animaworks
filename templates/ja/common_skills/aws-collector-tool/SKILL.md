---
name: aws-collector-tool
description: >-
  AWSインフラ監視ツール。ECSステータス確認・CloudWatchエラーログ取得・メトリクス取得。
  「AWS」「ECS」「CloudWatch」「インフラ」「メトリクス」「ログ」
tags: [infrastructure, aws, monitoring, external]
---

# AWS Collector ツール

AWS ECSステータス・CloudWatchログ・メトリクスを収集する外部ツール。

## use_tool での呼び出し

```json
{"tool": "use_tool", "arguments": {"tool_name": "aws_collector", "action": "ACTION", "args": {...}}}
```

## アクション一覧

### ecs_status — ECSサービス状態確認
```json
{"tool_name": "aws_collector", "action": "ecs_status", "args": {"cluster": "クラスタ名", "service": "サービス名(任意)"}}
```

### error_logs — エラーログ取得
```json
{"tool_name": "aws_collector", "action": "error_logs", "args": {"log_group": "ロググループ名", "hours": 1, "patterns": "ERROR,Exception"}}
```

### metrics — メトリクス取得
```json
{"tool_name": "aws_collector", "action": "metrics", "args": {"cluster": "クラスタ名", "service": "サービス名", "metric": "CPUUtilization", "hours": 1}}
```

## CLI使用法（Sモード）

```bash
animaworks-tool aws_collector ecs-status [--cluster NAME] [--service NAME]
animaworks-tool aws_collector error-logs --log-group NAME [--hours 1] [--patterns "ERROR"]
animaworks-tool aws_collector metrics --cluster NAME --service NAME [--metric CPUUtilization]
```

## 注意事項

- AWS認証情報（環境変数またはcredentials）の設定が必要
- --region でリージョン指定可能
