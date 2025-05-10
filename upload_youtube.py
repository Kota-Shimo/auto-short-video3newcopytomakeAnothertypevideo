# ================= upload_youtube.py =================
"""
YouTube へ動画をアップロードするユーティリティ。
複数アカウント対応（トークンを account ラベルで切替）。
"""

from pathlib import Path
from typing import List, Optional
import pickle, re, logging

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http      import MediaFileUpload
from google.auth.transport.requests import Request

# ── OAuth / API 設定 ─────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
DEFAULT_TOKEN_DIR = Path("tokens")          # トークン保存フォルダ
DEFAULT_TOKEN_DIR.mkdir(exist_ok=True)
# ────────────────────────────────────────────────────


# ------------------------------------------------------
# ✅ 追加: カスタムサムネイルをセットするヘルパー
def _set_thumbnail(service, video_id: str, thumb_path: Path):
    """アップロード済み video_id に thumb_path を適用"""
    service.thumbnails().set(
        videoId=video_id,
        media_body=str(thumb_path)
    ).execute()
# ------------------------------------------------------


def _get_service(account_label: str = "default"):
    """
    account_label : 任意の識別子。複数アカウントで token_<label>.pkl を使い分ける。
    """
    token_path = DEFAULT_TOKEN_DIR / f"token_{account_label}.pkl"

    if token_path.exists():
        creds = pickle.loads(token_path.read_bytes())
        # 有効期限切れなら自動リフレッシュ
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            "client_secret.json", SCOPES
        )
        creds = flow.run_local_server(port=0)
        token_path.write_bytes(pickle.dumps(creds))

    return build("youtube", "v3", credentials=creds)


# ── タイトル安全化（念のための最終チェック）────────────────
def _sanitize_title(raw: str) -> str:
    """空・改行入りを防ぎ、100字以内に丸める"""
    title = re.sub(r"[\s\u3000]+", " ", raw).strip()
    if len(title) > 100:
        title = title[:97] + "..."
    return title or "Auto Short #Shorts"
# ────────────────────────────────────────────────────


def upload(
    video_path: Path,
    title: str,
    desc: str,
    tags: Optional[List[str]] = None,
    privacy: str = "public",
    account: str = "default",
    thumbnail: Path | None = None,          # ★ 追加
):
    """
    video_path : Path to .mp4
    title      : YouTube title
    desc       : Description（0–5000 文字）
    tags       : ["tag1", ...]   (optional, 最大 500 個)
    privacy    : "public" / "unlisted" / "private"
    account    : token ラベル（複数アカウント切替用）
    thumbnail  : Path to .jpg / .png（カスタムサムネ）※任意
    """
    service = _get_service(account)

    # ---- 最終ガード ----
    title = _sanitize_title(title)
    if len(desc) > 5000:
        desc = desc[:4997] + "..."

    body = {
        "snippet": {
            "title":       title,
            "description": desc,
            "tags":        tags or [],
            "categoryId":  "27",        # 27 = Education
        },
        "status": {
            "privacyStatus": privacy,
        },
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    req   = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )
    resp = req.execute()

    video_id = resp["id"]
    url = f"https://youtu.be/{video_id}"
    print("✅ YouTube Upload Done →", url)

    # ---- カスタムサムネイル ----
    if thumbnail and thumbnail.exists():
        _set_thumbnail(service, video_id, thumbnail)
        print("🖼  Custom thumbnail set.")

    logging.info("YouTube URL: %s (account=%s)", url, account)
    return url
# ====================================================
