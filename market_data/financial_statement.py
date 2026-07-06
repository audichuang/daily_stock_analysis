"""Parse downloaded IFRS financial-statement HTML into sqlite tables.

Ported from the notebook-era module; parsing logic kept intact, deprecated
pandas ``applymap`` replaced with ``map``.
"""

import datetime
import os
import pickle
import re
import sqlite3

import numpy as np
import pandas as pd
from tqdm import tqdm


def afterIFRS(year, season):
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

    pickle.dump(
        ret,
        open(os.path.join("data", "financial_statement", f"pack{year}{season}.pickle"), "wb"),
    )
    return ret


def get_all_pickles(directory):
    ret = {}
    for i in os.listdir(directory):
        if i[:4] != "pack":
            continue
        ret[i[4:9]] = pd.read_pickle(os.path.join(directory, i))
    return ret


def combine(d):
    tnames = ["balance_sheet", "cash_flows", "income_sheet", "income_sheet_cumulate"]
    tbs = {t: pd.DataFrame() for t in tnames}
    for _, dfs in d.items():
        for tname in tnames:
            tbs[tname] = pd.concat([tbs[tname], dfs[tname]])
    return tbs


def fill_season4(tbs):
    income_sheet = tbs["income_sheet"].copy()
    c1 = set(tbs["income_sheet"].columns)
    c2 = set(tbs["income_sheet_cumulate"].columns)
    overlap_columns = ["累計" + i for i in c1 if "累計" + i in c2]

    years = set(tbs["income_sheet_cumulate"].index.levels[1].year)
    for y in years:
        cum = tbs["income_sheet_cumulate"].reset_index("stock_id")
        ys = cum.index.year == y
        ds4 = cum.index.month == 3
        df4 = (
            tbs["income_sheet_cumulate"][ds4 & ys]
            .apply(lambda s: pd.to_numeric(s, errors="coerce"))
            .reset_index("date")
        )
        yps = cum.index.year == y - 1
        ds3 = cum.index.month == 11
        df3 = (
            tbs["income_sheet_cumulate"][ds3 & yps]
            .apply(lambda s: pd.to_numeric(s, errors="coerce"))
            .reset_index("date")
        )
        if len(df3) == 0:
            print("skip", y)
            continue

        diff = (df4 - df3).drop(["date"], axis=1)[overlap_columns]
        diff.columns = diff.columns.str[2:]
        diff["date"] = pd.to_datetime(f"{y}-03-31")
        diff = diff[list(c1) + ["date"]].reset_index().set_index(["stock_id", "date"])
        income_sheet = pd.concat([income_sheet, diff])

    tbs["income_sheet"] = (
        income_sheet.reset_index()
        .sort_values(["stock_id", "date"])
        .set_index(["stock_id", "date"])
    )


def to_db(tbs):
    print("save table to db")
    conn = sqlite3.connect(os.path.join("data", "data.db"))
    for i, df in tbs.items():
        print("  ", i)
        df = (
            df.reset_index()
            .sort_values(["stock_id", "date"])
            .drop_duplicates(["stock_id", "date"])
            .set_index(["stock_id", "date"])
        )
        df[df.count().nlargest(900).index].to_sql(i, conn, if_exists="replace")
    conn.close()


def html2db(date):
    year = date.year
    if date.month == 3:
        season, year = 4, year - 1
    elif date.month == 5:
        season = 1
    elif date.month == 8:
        season = 2
    elif date.month == 11:
        season = 3
    else:
        return None

    directory = os.path.join("data", "financial_statement", f"{year}{season}")
    pack_htmls(year, season, directory)
    d = get_all_pickles(os.path.join("data", "financial_statement"))
    tbs = combine(d)
    fill_season4(tbs)
    to_db(tbs)
    return {}
