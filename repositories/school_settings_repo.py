"""학교 정보는 현재 암호화 DB에 함께 보관한다."""

from database import Database
from models import SchoolSettings


class SchoolSettingsRepository:
    def __init__(self, database: Database):
        self.database = database

    def get(self) -> SchoolSettings:
        with self.database.session() as connection:
            row = connection.execute('''SELECT school_name, school_level, counselor_name, office_number
                FROM school_settings WHERE id=1''').fetchone()
        return SchoolSettings.model_validate(dict(row)) if row else SchoolSettings()

    def save(self, settings: SchoolSettings) -> SchoolSettings:
        settings = SchoolSettings.model_validate(settings.model_dump())
        with self.database.session(write=True) as connection:
            connection.execute('''INSERT INTO school_settings
                (id, school_name, school_level, counselor_name, office_number)
                VALUES (1, :school_name, :school_level, :counselor_name, :office_number)
                ON CONFLICT(id) DO UPDATE SET school_name=excluded.school_name,
                    school_level=excluded.school_level, counselor_name=excluded.counselor_name,
                    office_number=excluded.office_number''', settings.model_dump())
        return settings
