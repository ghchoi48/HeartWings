"""새 DB에만 최초 설정 진행 상태를 보관한다. 기존 DB는 설정을 반복하지 않는다."""


class OnboardingRepository:
    def __init__(self, database):
        self.database = database

    def get(self):
        with self.database.session() as connection:
            if not connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='onboarding_state'"
            ).fetchone():
                return None
            row = connection.execute('SELECT step FROM onboarding_state WHERE id=1').fetchone()
            return row['step'] if row else None

    def save(self, step):
        if step not in ('school', 'choice', 'legacy', 'roster', 'welcome', 'complete'):
            raise ValueError('잘못된 최초 설정 단계입니다.')
        with self.database.session(write=True) as connection:
            connection.execute('UPDATE onboarding_state SET step=? WHERE id=1', (step,))
