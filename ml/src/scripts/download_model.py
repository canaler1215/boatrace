"""
GitHub Releases から最新の学習済みモデルをダウンロードする

環境変数:
  GITHUB_TOKEN      : GitHub Personal Access Token（または GITHUB_TOKEN シークレット）
  GITHUB_REPOSITORY : "owner/repo" 形式（GitHub Actions では自動設定）
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ARTIFACTS_DIR = Path(__file__).parents[3] / "artifacts"


def _gh_request(url: str, token: str, accept: str = "application/vnd.github+json") -> urllib.request.Request:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", accept)
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    return req


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")

    if not repo:
        print("ERROR: GITHUB_REPOSITORY is not set.", file=sys.stderr)
        sys.exit(1)

    # GitHub API でリリース一覧を取得
    api_url = f"https://api.github.com/repos/{repo}/releases"
    with urllib.request.urlopen(_gh_request(api_url, token)) as resp:
        releases = json.loads(resp.read())

    # model-* タグのリリースを最新順で探す
    model_release = next(
        (r for r in releases if r["tag_name"].startswith("model-")),
        None,
    )
    if model_release is None:
        print("ERROR: No model release found on GitHub Releases.", file=sys.stderr)
        sys.exit(1)

    print(f"Found release: {model_release['tag_name']}")

    # .pkl アセットを探す
    pkl_asset = next(
        (a for a in model_release["assets"] if a["name"].endswith(".pkl")),
        None,
    )
    if pkl_asset is None:
        print(f"ERROR: No .pkl asset in release {model_release['tag_name']}.", file=sys.stderr)
        sys.exit(1)

    # ダウンロード（Bearer + octet-stream でリダイレクト先から取得）
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    dest = ARTIFACTS_DIR / "model_latest.pkl"

    print(f"Downloading {pkl_asset['name']} ...")
    dl_req = _gh_request(pkl_asset["url"], token, accept="application/octet-stream")
    with urllib.request.urlopen(dl_req) as resp:
        data = resp.read()

    dest.write_bytes(data)
    print(f"Saved to {dest} ({len(data):,} bytes)")


if __name__ == "__main__":
    main()
