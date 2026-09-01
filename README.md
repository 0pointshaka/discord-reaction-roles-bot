7. 管理者は `!post_reaction` で監視用メッセージを投稿、または `!set_message <message_id>` で既存メッセージを監視対象にできます。
8. `!export_auth_csv` で最新ログを CSV ダウンロードできます（manage_roles 権限が必要）。

## ログ
- CSV は `logs/auth_log.csv` に出力されます。
- フィールド: timestamp,guild_id,guild_name,user_id,user_name,action,emoji,role_id,message_id

## 注意
- token は絶対に公開しないでください（config.json は .gitignore に入っています）。
- GDPR 等、個人情報の扱いに注意してください。
