"""Open-Meteo 지역 검색 및 현재·7일 예보 조회."""
import json
import math
import ssl
import sys
from datetime import date
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import certifi


# 두 글자 검색은 정확히 일치하는 지명만 반환하므로 국내 통용명을 공식 지명으로 확장한다.
KOREAN_REGIONS = {
    '서울': '서울특별시', '부산': '부산광역시', '대구': '대구광역시',
    '인천': '인천광역시', '광주': '광주광역시', '대전': '대전광역시',
    '울산': '울산광역시', '세종': '세종특별자치시', '제주': '제주시',
}


class WeatherError(RuntimeError):
    pass


def coordinates(latitude, longitude):
    if (type(latitude) not in (int, float) or type(longitude) not in (int, float)
            or not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise ValueError('올바른 지역 좌표가 아닙니다.')
    return latitude, longitude


def _ssl_context():
    if sys.platform != 'win32':
        return ssl.create_default_context(cafile=certifi.where())

    # Include Windows-trusted certificates (e.g. a school's HTTPS proxy CA)
    # as well as the bundled public roots.
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    # Python 3.13+ enables strict X.509 format checks. Older enterprise CAs
    # can lack Authority Key Identifier; retain chain and hostname validation
    # while using the pre-3.13 format compatibility on Windows.
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def request(url, params):
    try:
        with urlopen(url + '?' + urlencode(params), timeout=12,
                     context=_ssl_context()) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError()
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('error'):
            raise ValueError()
        return data
    except (OSError, URLError, TimeoutError):
        raise WeatherError('날씨 서비스에 연결하지 못했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요.') from None
    except (ValueError, TypeError):
        raise WeatherError('날씨 응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요.') from None


def search_regions(query):
    query = query.strip()
    if not 2 <= len(query) <= 100:
        raise WeatherError('지역명을 2~100자로 입력해 주세요.')
    params = {'name': KOREAN_REGIONS.get(query, query), 'count': 10, 'language': 'ko', 'format': 'json'}
    if query in KOREAN_REGIONS:
        params['countryCode'] = 'KR'
    payload = request('https://geocoding-api.open-meteo.com/v1/search', params)
    try:
        results = []
        for row in payload.get('results', []):
            lat, lon = coordinates(row['latitude'], row['longitude'])
            label = ' · '.join(dict.fromkeys(str(row[key]) for key in ('name', 'admin2', 'admin1', 'country') if row.get(key)))
            results.append({'name': label, 'latitude': lat, 'longitude': lon})
        return results
    except (KeyError, TypeError, ValueError):
        raise WeatherError('지역 검색 결과를 읽지 못했습니다.') from None


def fetch_weather(latitude, longitude):
    coordinates(latitude, longitude)
    data = request('https://api.open-meteo.com/v1/forecast', {
        'latitude': latitude, 'longitude': longitude, 'timezone': 'auto', 'forecast_days': 7,
        'current': 'temperature_2m,weather_code,is_day',
        'daily': 'weather_code,temperature_2m_min,temperature_2m_max',
    })
    try:
        def number(value):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError()
            return value
        current, daily = data['current'], data['daily']
        days = []
        for i, day in enumerate(daily['time']):
            days.append({'date': date.fromisoformat(day), 'code': number(daily['weather_code'][i]),
                         'low': number(daily['temperature_2m_min'][i]),
                         'high': number(daily['temperature_2m_max'][i])})
        if not days:
            raise ValueError()
        return {'temperature': number(current['temperature_2m']), 'code': number(current['weather_code']),
                'is_day': current.get('is_day', 1) == 1, 'time': str(current['time']), 'days': days[:7]}
    except (KeyError, IndexError, TypeError, ValueError):
        raise WeatherError('날씨 예보가 아직 제공되지 않습니다. 잠시 후 다시 시도해 주세요.') from None


def weather_status(code, is_day=True):
    if code == 0:
        return ('맑음', 'wb_sunny' if is_day else 'nightlight_round')
    if code in (1, 2):
        return ('구름 조금' if code == 1 else '구름 많음', 'wb_cloudy')
    if code == 3:
        return ('흐림', 'cloud')
    if code in (45, 48):
        return ('안개', 'blur_on')
    if code in (51, 53, 55, 56, 57):
        return ('이슬비', 'grain')
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return ('비', 'umbrella')
    if code in (71, 73, 75, 77, 85, 86):
        return ('눈', 'ac_unit')
    if code in (95, 96, 99):
        return ('뇌우', 'thunderstorm')
    return ('날씨 정보 없음', 'help_outline')
