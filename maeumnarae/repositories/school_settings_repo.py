"""학교 정보는 현재 암호화 DB에 함께 보관한다."""

from maeumnarae.core.database import Database
from maeumnarae.core.models import SchoolSettings


class SchoolSettingsRepository:
    def __init__(self, database: Database):
        self.database = database

    def get(self) -> SchoolSettings:
        with self.database.session() as connection:
            row = connection.execute('''SELECT school_name, school_level, counselor_name, office_number,
                neis_office_code, neis_school_code, neis_api_key
                FROM school_settings WHERE id=1''').fetchone()
        return SchoolSettings.model_validate(dict(row)) if row else SchoolSettings()

    def save(self, settings: SchoolSettings) -> SchoolSettings:
        settings = SchoolSettings.model_validate(settings.model_dump())
        with self.database.session(write=True) as connection:
            connection.execute('''INSERT INTO school_settings
                (id, school_name, school_level, counselor_name, office_number, neis_office_code, neis_school_code, neis_api_key)
                VALUES (1, :school_name, :school_level, :counselor_name, :office_number, :neis_office_code, :neis_school_code, :neis_api_key)
                ON CONFLICT(id) DO UPDATE SET school_name=excluded.school_name,
                    school_level=excluded.school_level, counselor_name=excluded.counselor_name,
                    office_number=excluded.office_number, neis_office_code=excluded.neis_office_code,
                    neis_school_code=excluded.neis_school_code, neis_api_key=excluded.neis_api_key''', settings.model_dump())
        return settings
