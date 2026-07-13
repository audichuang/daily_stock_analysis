"""TWSE / MOPS scrapers and parsers.

Ported from the notebook-era crawler: kept the proven parsing logic, removed
notebook-only orchestration (ipywidgets / tqdm_notebook), fixed import order and
deprecated pandas calls. Network functions are exercised by a live smoke test,
not unit tests.
"""

import datetime
import os
import shutil
import time
import urllib.request
import warnings
import zipfile
from io import StringIO

import pandas as pd
import requests
from requests.exceptions import ConnectionError, ReadTimeout
from tqdm import tqdm

warnings.simplefilter(action="ignore", category=FutureWarning)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


def _headers():
    return {"Accept": "*/*", "Connection": "keep-alive", "User-Agent": _UA}


_session = None


def _find_session():
    global _session
    for i in range(10):
        try:
            ses = requests.Session()
            ses.headers.update(_headers())
            ses.get("https://www.twse.com.tw/zh/", timeout=10)
            _session = ses
            return ses
        except (ConnectionError, ReadTimeout) as error:
            print(error, "- retry session in 10s")
            time.sleep(10)
    raise RuntimeError("無法建立 session,你的 IP 可能被 TWSE 暫時封鎖,請更換 IP")


def _request(method, *args, **kwargs):
    if _session is None:
        _find_session()
    kwargs.setdefault("timeout", 10)
    for i in range(4):
        try:
            return getattr(_session, method)(*args, **kwargs)
        except (ConnectionError, ReadTimeout) as error:
            print(error, f"- retry after 60s ({3 - i} left)")
            time.sleep(60)
            _find_session()
    return None


def requests_get(*args, **kwargs):
    return _request("get", *args, **kwargs)


def crawl_price(date):
    datestr = date.strftime("%Y%m%d")
    r = _request(
        "post",
        "https://www.twse.com.tw/exchangeReport/MI_INDEX"
        f"?response=csv&date={datestr}&type=ALLBUT0999"
    )
    if r is None:
        print("**WARN: cannot get stock price at", datestr)
        return None

    content = r.text.replace("=", "")
    lines = [ln for ln in content.split("\n") if len(ln.split('",')) > 10]
    content = "\n".join(lines)
    if content == "":
        return None

    df = pd.read_csv(StringIO(content))
    df = df.astype(str).apply(lambda s: s.str.replace(",", ""))
    df["date"] = pd.to_datetime(date)
    df = df.rename(columns={"證券代號": "stock_id"}).set_index(["stock_id", "date"])
    df = df.apply(lambda s: pd.to_numeric(s, errors="coerce"))
    df = df[df.columns[~df.isnull().all()]]
    df = df[~df["收盤價"].isnull()]
    return df


def crawl_monthly_report(date):
    url = (
        "https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_"
        f"{date.year - 1911}_{date.month}.html"
    )
    print(url)
    r = requests_get(url, headers={"User-Agent": _UA}, verify=False)
    if r is None:
        print("**WARN: requests cannot get html")
        return None
    r.encoding = "big5"

    try:
        html_df = pd.read_html(StringIO(r.text))
    except ValueError:
        print("**WARN: Pandas cannot find any table in the HTML file")
        return None

    if html_df[0].shape[0] > 500:
        df = html_df[0].copy()
    else:
        # Old segmented layout (民國100-101): many per-industry tables. Most carry
        # MultiIndex headers but a stray plain-header table sneaks in; concatenating
        # the mix corrupts the columns. Keep only the MultiIndex tables when present.
        candidates = [d for d in html_df if 5 < d.shape[1] <= 11]
        multiindex = [d for d in candidates if "levels" in dir(d.columns)]
        df = pd.concat(multiindex if multiindex else candidates)

    if "levels" in dir(df.columns):
        df.columns = df.columns.get_level_values(1)
        df.columns = df.columns.str.replace(" ", "")
    else:
        df = df[list(range(0, 10))]
        header_rows = df.index[(df[0] == "公司代號")]
        if len(header_rows) == 0:
            # pre-~2013 monthly reports use a different layout we don't parse
            print("**WARN: unrecognised monthly-report format, skipping", url)
            return None
        df.columns = df.iloc[header_rows[0]]

    df["當月營收"] = pd.to_numeric(df["當月營收"], errors="coerce")
    df = df[~df["當月營收"].isnull()]
    df = df[df["公司代號"] != "合計"]

    next_month = datetime.date(
        date.year + int(date.month / 12), (date.month % 12) + 1, 10
    )
    df["date"] = pd.to_datetime(next_month)
    df = df.rename(columns={"公司代號": "stock_id"}).set_index(["stock_id", "date"])
    df = df.apply(lambda s: pd.to_numeric(s, errors="coerce"))
    df = df[df.columns[~df.isnull().all()]]
    return df


def crawl_finance_statement2019(year, season):
    url = (
        "https://mopsov.twse.com.tw/server-java/FileDownLoad?step=9&fileName=tifrs-"
        f"{year}Q{season}.zip&filePath=/home/html/nas/ifrs/{year}/"
    )
    print("start download", url)

    class _Bar(tqdm):
        def update_to(self, b=1, bsize=1, tsize=None):
            if tsize is not None:
                self.total = tsize
            self.update(b * bsize - self.n)

    with _Bar(unit="B", unit_scale=True, miniters=1, desc="ifrs.zip") as t:
        urllib.request.urlretrieve(url, "temp.zip", reporthook=t.update_to)
    print("finish download")

    path = os.path.join("data", "financial_statement", f"{year}{season}")
    if os.path.isdir(path):
        shutil.rmtree(path)

    with zipfile.ZipFile(open("temp.zip", "rb")) as zf:
        zf.extractall(path=path)

    fnames = sorted(f for f in os.listdir(path) if f.endswith(".html"))
    for fold in fnames:
        fnew = fold.split("-")[5] + ".html"
        if len(fnew) != 9:
            os.remove(os.path.join(path, fold))
            continue
        dst = os.path.join(path, fnew)
        if not os.path.exists(dst):
            os.rename(os.path.join(path, fold), dst)
        else:
            os.remove(os.path.join(path, fold))
