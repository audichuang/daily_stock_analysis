"""Parse downloaded IFRS financial-statement HTML into wide quarter frames.

Ported from the notebook-era module; parsing logic kept intact, deprecated
pandas ``applymap`` replaced with ``map``. Persistence lives in
``crawl.crawl_financials`` (long-format upsert into Postgres); the old
sqlite/pickle pipeline is gone.
"""

import datetime
import os
import re

import numpy as np
import pandas as pd
from tqdm import tqdm


def afterIFRS(year, season):
    """財報 `date` 欄用的公告截止日（一般公司：季報 45 日內、年報次年 3/31）。

    **這是全公司一律套同一天的簡化，對金融保險業（金控／銀行／票券／保險）不成立**——
    它們的季報截止日是 60 日內（Q1 5/30、Q3 11/29）、半年報 8/31，比這裡寫的早 15 天。
    拿這張表做 point-in-time 對齊時，金融保險業會有約 15 天的前視。目前的回測與選股
    都不讀 `financial_statement`，所以沒有實際影響；**要加 quality／ROE 因子時，
    最省的處理是直接把金融保險業排除在該因子的宇宙外**（銀行保險的 ROE／PB 本來就
    與工業股不可比，這是因子研究的標準做法），而不是為此維護一份晚報公司清單。
    """
    season2date = [
        datetime.datetime(year, 5, 15),
        datetime.datetime(year, 8, 14),
        datetime.datetime(year, 11, 14),
        datetime.datetime(year + 1, 3, 31),
    ]
    return pd.to_datetime(season2date[season - 1].date())


def clean(year, season, balance_sheet):
    if len(balance_sheet) == 0:
        print("**WARN: no data to parse")
        return balance_sheet
    balance_sheet = balance_sheet.transpose().reset_index().rename(
        columns={"index": "stock_id"}
    )
    if "會計項目" in balance_sheet:
        s = balance_sheet["會計項目"]
        balance_sheet = balance_sheet.drop("會計項目", axis=1).apply(pd.to_numeric)
        balance_sheet["會計項目"] = s.astype(str)
    balance_sheet["date"] = afterIFRS(year, season)
    balance_sheet["stock_id"] = balance_sheet["stock_id"].astype(str)
    return balance_sheet.set_index(["stock_id", "date"])


def remove_english(s):
    return re.sub(r"[a-zA-Z()]", "", s)


def patch2019(df):
    df = df.copy()
    dfname = df.columns.levels[0][0]
    df = df.iloc[:, 1:].rename(columns={"會計項目Accounting Title": "會計項目"})
    refined_name = (
        df[(dfname, "會計項目")]
        .str.split(" ")
        .str[0]
        .str.replace("　", "")
        .apply(remove_english)
    )
    subdf = df[dfname].copy()
    subdf["會計項目"] = refined_name
    df[dfname] = subdf
    df.columns = pd.MultiIndex(
        levels=[df.columns.levels[1], df.columns.levels[0]],
        codes=[df.columns.codes[1], df.columns.codes[0]],
    )

    def neg(s):
        if isinstance(s, float):
            return s
        if str(s) == "nan":
            return np.nan
        s = s.replace(",", "")
        return -float(s[1:-1]) if s[0] == "(" else float(s)

    # Rebuild instead of in-place ``df.iloc[:, 1:] = ...``: the numeric columns
    # arrive as str dtype and pandas 2.2 refuses to store floats back into a
    # str column ("Invalid value ... for dtype 'str'").
    numeric = df.iloc[:, 1:].map(neg)
    df = pd.concat([df.iloc[:, [0]], numeric], axis=1)
    return df


def read_html2019(file):
    dfs = pd.read_html(file)
    return [pd.DataFrame(), patch2019(dfs[0]), patch2019(dfs[1]), patch2019(dfs[2])]


def pack_htmls(year, season, directory):
    balance_sheet = {}
    income_sheet = {}
    cash_flows = {}
    income_sheet_cumulate = {}
    pbar = tqdm(os.listdir(directory))

    for i in pbar:
        file = os.path.join(directory, i)
        if file[-4:] != "html" or os.stat(file).st_size < 10000:
            continue
        stock_id = i.split(".")[0]
        pbar.set_description(f"parse {year}Q{season} stock {stock_id}")

        if year < 2019:
            dfs = pd.read_html(file)
        else:
            try:
                dfs = read_html2019(file)
            except Exception as e:
                # one unparseable stock must not abort the whole quarter
                print(f"**WARN cannot parse {file}: {type(e).__name__}: {e}"[:200])
                continue

        for df in dfs:
            if "levels" in dir(df.columns):
                df.columns = list(range(df.values.shape[1]))

        if len(dfs) < 4:
            print("**WARN html file broken", year, season, i)
            continue

        df = dfs[1].copy().drop_duplicates(subset=0, keep="last").set_index(0)
        balance_sheet[stock_id] = df[1].dropna()

        df = dfs[2].copy().drop_duplicates(subset=0, keep="last").set_index(0)
        if len(df.columns) == 4:
            income_sheet[stock_id] = df[1].dropna()
            income_sheet_cumulate[stock_id] = df[3].dropna()
        elif len(df.columns) == 2:
            income_sheet_cumulate[stock_id] = df[1].dropna()
            if season == 1:
                income_sheet[stock_id] = df[1].dropna()

        df = dfs[3].copy().drop_duplicates(subset=0, keep="last").set_index(0)
        cash_flows[stock_id] = df[1].dropna()

    ret = {
        "balance_sheet": clean(year, season, pd.DataFrame(balance_sheet)),
        "income_sheet": clean(year, season, pd.DataFrame(income_sheet)),
        "income_sheet_cumulate": clean(
            year, season, pd.DataFrame(income_sheet_cumulate)
        ),
        "cash_flows": clean(year, season, pd.DataFrame(cash_flows)),
    }
    if season == 1:
        ret["income_sheet"] = ret["income_sheet_cumulate"].copy()
    ret["income_sheet_cumulate"].columns = "累計" + ret["income_sheet_cumulate"].columns
    return ret
