import logging
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

logger = logging.getLogger(__name__)

from configs import config
if config.DB_ENABLED:
    engine = create_engine(config.DATABASE_URI,pool_size=config.POOL_SIZE)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Dependency
    def get_session()-> Optional[Session]:
        session  = SessionLocal()
        return session

    @contextmanager
    def get_db() -> Generator[Session, None, None]:
        with get_session() as session:
            try:
                yield session
            finally:
                session.close()
else:
    logger.info("Database is not enabled, skipping database setup.")
    engine = None
    SessionLocal = None

    # Dependency
    def get_session()-> Optional[Session]:
        return None

    @contextmanager
    def get_db() -> Generator[Optional[Session], None, None]:
        yield None