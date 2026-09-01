import json
import logging
import asyncio
import discord
from discord.ext import commands
import datetime
import os
import csv
import io

# ログ設定
logging.basicConfig(level=logging.INFO)

# 設定読み込み
with open("config.json", "r", encoding="utf-8") as f:
    cfg = json.load(f)

TOKEN = cfg.get("token", "REPLACE_ME")
GUILD_ID = cfg.get("guild_id")          # 任意: 特定サーバーに限定する場合
MESSAGE_ID = cfg.get("message_id")      # 監視するメッセージID（後でコマンドで設定可能）
EMOJI_ROLE_MAP = cfg.get("emoji_role_map", {})  # 例: {"✅": 123456789012345678, "<:custom:111222333>": 9876543210}
BOT_PREFIX = cfg.get("prefix", "!")

# ログ周り
LOG_DIR = cfg.get("log_dir", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
AUTH_CSV_PATH = os.path.join(LOG_DIR, "auth_log.csv")
CSV_FIELDS = ["timestamp","guild_id","guild_name","user_id","user_name","action","emoji","role_id","message_id"]

def ensure_csv_header():
    if not os.path.exists(AUTH_CSV_PATH):
        with open(AUTH_CSV_PATH, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()

def write_auth_log_csv(entry: dict):
    entry.setdefault("timestamp", datetime.datetime.utcnow().isoformat() + "Z")
    ensure_csv_header()
    with open(AUTH_CSV_PATH, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writerow({
            "timestamp": entry.get("timestamp"),
            "guild_id": entry.get("guild_id"),
            "guild_name": entry.get("guild_name"),
            "user_id": entry.get("user_id"),
            "user_name": entry.get("user_name"),
            "action": entry.get("action"),
            "emoji": entry.get("emoji"),
            "role_id": entry.get("role_id"),
            "message_id": entry.get("message_id"),
        })

intents = discord.Intents.default()
intents.members = True  # Server Members Intent を Portal で ON にしてください
intents.guilds = True
intents.reactions = True

bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents, help_command=None)


def save_config():
    cfg["message_id"] = MESSAGE_ID
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (id: {bot.user.id})")
    logging.info("Ready.")


@bot.command(name="post_reaction")
@commands.has_guild_permissions(manage_roles=True)
async def post_reaction(ctx, *, text: str = None):
    """
    Bot が反応用メッセージを投稿し、config の絵文字をリアクションとして付与します。
    使い方: !post_reaction [任意テキスト]
    """
    global MESSAGE_ID
    if text is None:
        text = "リアクションでロールを付与します:\n" + "\n".join(f"{emoji} → <@&{role_id}>" for emoji, role_id in EMOJI_ROLE_MAP.items())
    msg = await ctx.send(text)
    # 絵文字を付ける
    for emoji in EMOJI_ROLE_MAP.keys():
        try:
            await msg.add_reaction(emoji)
            await asyncio.sleep(0.2)
        except Exception as e:
            logging.warning(f"リアクション追加失敗: {emoji} - {e}")
    MESSAGE_ID = msg.id
    cfg["message_id"] = MESSAGE_ID
    save_config()
    await ctx.send(f"監視メッセージを投稿しました (ID: {MESSAGE_ID})")


@bot.command(name="set_message")
@commands.has_guild_permissions(manage_roles=True)
async def set_message(ctx, message_id: int):
    """
    既存メッセージを監視対象として設定します。
    使い方: !set_message 123456789012345678
    """
    global MESSAGE_ID
    MESSAGE_ID = message_id
    cfg["message_id"] = MESSAGE_ID
    save_config()
    await ctx.send(f"監視メッセージを設定しました: {MESSAGE_ID}")


async def add_role_by_id(guild: discord.Guild, user_id: int, role_id: int):
    try:
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        role = guild.get_role(role_id)
        if member is None or role is None:
            logging.warning("member または role が見つかりません")
            return
        await member.add_roles(role, reason="Reaction role add")
        logging.info(f"Added role {role.name} to {member}")
    except Exception as e:
        logging.exception("ロール付与エラー")


async def remove_role_by_id(guild: discord.Guild, user_id: int, role_id: int):
    try:
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        role = guild.get_role(role_id)
        if member is None or role is None:
            logging.warning("member または role が見つかりません")
            return
        await member.remove_roles(role, reason="Reaction role remove")
        logging.info(f"Removed role {role.name} from {member}")
    except Exception as e:
        logging.exception("ロール解除エラー")


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    try:
        if MESSAGE_ID is None:
            return
        if payload.message_id != MESSAGE_ID:
            return
        guild = bot.get_guild(payload.guild_id)
        if guild is None:
            return
        emoji_key = str(payload.emoji)
        role_id = EMOJI_ROLE_MAP.get(emoji_key)
        if role_id is None:
            alt_key = payload.emoji.name if hasattr(payload.emoji, "name") else None
            role_id = EMOJI_ROLE_MAP.get(alt_key)
        if role_id:
            await add_role_by_id(guild, payload.user_id, int(role_id))
            # CSV ログ追記
            try:
                member = guild.get_member(payload.user_id)
                write_auth_log_csv({
                    "guild_id": guild.id,
                    "guild_name": guild.name,
                    "user_id": payload.user_id,
                    "user_name": f"{member.name}#{member.discriminator}" if member else None,
                    "action": "role_add",
                    "emoji": emoji_key,
                    "role_id": int(role_id),
                    "message_id": payload.message_id,
                })
            except Exception:
                logging.exception("auth log write failed")
    except Exception:
        logging.exception("on_raw_reaction_add error")


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    try:
        if MESSAGE_ID is None:
            return
        if payload.message_id != MESSAGE_ID:
            return
        guild = bot.get_guild(payload.guild_id)
        if guild is None:
            return
        emoji_key = str(payload.emoji)
        role_id = EMOJI_ROLE_MAP.get(emoji_key)
        if role_id is None:
            alt_key = payload.emoji.name if hasattr(payload.emoji, "name") else None
            role_id = EMOJI_ROLE_MAP.get(alt_key)
        if role_id:
            await remove_role_by_id(guild, payload.user_id, int(role_id))
            # CSV ログ追記
            try:
                member = guild.get_member(payload.user_id)
                write_auth_log_csv({
                    "guild_id": guild.id,
                    "guild_name": guild.name,
                    "user_id": payload.user_id,
                    "user_name": f"{member.name}#{member.discriminator}" if member else None,
                    "action": "role_remove",
                    "emoji": emoji_key,
                    "role_id": int(role_id),
                    "message_id": payload.message_id,
                })
            except Exception:
                logging.exception("auth log write failed")
    except Exception:
        logging.exception("on_raw_reaction_remove error")


@bot.command(name="export_auth_csv")
@commands.has_guild_permissions(manage_roles=True)
async def export_auth_csv(ctx, lines: int = 500):
    """最新 N 行を CSV ファイルで出力して送信（デフォルト 500 行）"""
    if not os.path.exists(AUTH_CSV_PATH):
        await ctx.send("認証ログが見つかりません。")
        return
    # 全行読み込みして末尾を取る（小〜中規模のログなら問題なし）
    with open(AUTH_CSV_PATH, "r", encoding="utf-8", newline="") as f:
        all_lines = f.readlines()
    # 最低限 header は残す
    header = all_lines[0] if all_lines else ""
    tail = all_lines[-lines:] if len(all_lines) > 1 else all_lines
    out = "".join([header] + [l for l in tail if l != header])
    fname = f"auth_log_{ctx.guild.id}_{int(datetime.datetime.utcnow().timestamp())}.csv"
    await ctx.send(file=discord.File(fp=io.StringIO(out), filename=fname))


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("権限が不足しています (manage_roles が必要です)。")
    else:
        logging.exception("Command error")
        await ctx.send(f"エラー: {error}")


if __name__ == "__main__":
    ensure_csv_header()
    bot.run(TOKEN)
