# profile_sidebar.py
from __future__ import annotations
import re, json, os
from pathlib import Path
import streamlit as st

# 🔐 안전한 임포트: 루트/패키지 경로 모두 시도 + 마지막엔 로컬 구현 폴백
ROOT = Path(__file__).resolve().parent
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    # 루트에 utils_common.py 있는 경우
    from utils_common import extract_sheet_id, sheet_link, save_env_value
except Exception:
    try:
        # 패키지 안에 있는 경우
        from item_uploader.utils_common import extract_sheet_id, sheet_link, save_env_value
    except Exception:
        # 🔁 최후 폴백: 최소 기능 로컬 구현
        def extract_sheet_id(s: str) -> str | None:
            s = (s or "").strip()
            m = re.search(r"/spreadsheets/d/([A-Za-z0-9\-_]+)", s)
            if m: return m.group(1)
            if re.fullmatch(r"[A-Za-z0-9\-_]{25,}", s): return s
            return None
        def sheet_link(sid: str) -> str:
            return f"https://docs.google.com/spreadsheets/d/{sid}/edit"
        def save_env_value(key: str, value: str):
            # 로컬 개발용 - .env 간단 갱신
            env_path = ROOT / ".env"
            kv = {}
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    if line.strip() and not line.strip().startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        kv[k.strip()] = v.strip()
            kv[key] = value
            env_path.write_text("\n".join(f"{k}={v}" for k, v in kv.items()) + "\n", encoding="utf-8")
