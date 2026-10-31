"""行事曆快取的持久層；請求端只有 SELECT，外部更新由排程執行。"""
from sqlalchemy import delete, select

from src.storage import CalendarEventRecord, DatabaseManager


class CalendarRepository:
    def __init__(self, db_manager=None):
        self.db = db_manager or DatabaseManager.get_instance()

    def read(self, codes, start, end):
        with self.db.get_session() as session:
            rows = session.execute(select(CalendarEventRecord).where(
                (CalendarEventRecord.code.in_(list(codes))) | CalendarEventRecord.code.is_(None),
                (CalendarEventRecord.date.is_(None))
                | CalendarEventRecord.date.between(start, end),
            )).scalars().all()
            return [{c.name: getattr(row, c.name) for c in row.__table__.columns} for row in rows]

    def save_earnings(self, row):
        with self.db.get_session() as session:
            session.merge(CalendarEventRecord(**row))
            session.commit()

    def replace_macro_type(self, kind, rows):
        # 同一類型成功抓完才替換；失敗時不呼叫，保留仍在有效期內的快取。
        # 新資料只涵蓋到最後一天：更遠的日期（例如跨年備援暫時失敗）不刪，交給快取效期淘汰。
        last_day = max(r["date"] for r in rows)
        with self.db.get_session() as session:
            session.execute(delete(CalendarEventRecord).where(
                CalendarEventRecord.code.is_(None), CalendarEventRecord.type == kind,
                CalendarEventRecord.date <= last_day,
            ))
            session.add_all([CalendarEventRecord(**r) for r in rows])
            session.commit()

    def replace_type(self, kind, rows):
        # 法說會一次抓完所有月份才替換，失敗時不呼叫。
        with self.db.get_session() as session:
            session.execute(delete(CalendarEventRecord).where(CalendarEventRecord.type == kind))
            session.add_all([CalendarEventRecord(**r) for r in rows])
            session.commit()
