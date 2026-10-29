import os
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Database:
    def __init__(self) -> None:
        uri = os.getenv("MONGODB_URI", "mongodb+srv://trancongdanh044_db_user:4sYl9i55DyzDd1VF@cluster0.pv38pja.mongodb.net/ai_scientist")
        db_name = os.getenv("MONGODB_DB", "ai_scientist")
        self.client = AsyncIOMotorClient(uri)
        self.db = self.client[db_name]
        print(f"Địa chỉ databse {uri}")
        self.runs = self.db.runs
        self.stages = self.db.stages
        self.papers = self.db.papers
        self.hypotheses = self.db.hypotheses
        self.sections = self.db.sections
        self.reviews = self.db.reviews
        self.files = self.db.files

    async def init_indexes(self) -> None:
        await self.runs.create_index([("created_at", DESCENDING)])
        await self.stages.create_index([("run_id", ASCENDING), ("ts", ASCENDING)])
        await self.papers.create_index("run_id", unique=True)
        await self.hypotheses.create_index("run_id", unique=True)
        await self.sections.create_index([("run_id", ASCENDING), ("order", ASCENDING)])
        await self.reviews.create_index("run_id", unique=True)
        await self.files.create_index([("run_id", ASCENDING), ("name", ASCENDING)])

    async def test_connection(self) -> bool:
        """Kiểm tra kết nối đến MongoDB Atlas/Server thành công hay không."""
        try:
            # Lệnh ping sẽ gửi một yêu cầu xác thực và kiểm tra phản hồi từ cụm MongoDB
            await self.client.admin.command("ping")
            print(" Kết nối Database thành công!")
            return True
        except Exception as e:
            print(f" Kết nối Database thất bại: {e}")
            return False

    async def close(self) -> None:
        self.client.close()


db = Database()