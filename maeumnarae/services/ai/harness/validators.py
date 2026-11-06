from .types import Draft, ValidationIssue


def validate_output(raw, definition, note):
    draft = Draft.model_validate_json(raw)
    ids = [f.id for f in draft.fields]
    if len(set(ids)) != len(ids) or set(ids) != {f.id for f in definition.fields}:
        raise ValueError('출력 항목이 일치하지 않습니다.')
    values = {f.id: f for f in draft.fields}
    ordered, issues = [], []
    for field in definition.fields:
        value = values[field.id]
        if not value.text.strip():
            raise ValueError('빈 출력입니다.')
        ordered.append(value)
        if value.text.strip() == '확인 필요':
            issues.append(ValidationIssue(code='missing_information', field_id=field.id,
                                          message='원문 정보가 부족합니다. 내용을 확인해 주세요.'))
        elif field.evidence_required and not value.evidence:
            issues.append(ValidationIssue(code='missing_evidence', field_id=field.id,
                                          message='원문 근거가 제시되지 않았습니다.'))
        if any(not quote.strip() or quote not in note for quote in value.evidence):
            issues.append(ValidationIssue(code='unmatched_evidence', field_id=field.id,
                                          message='원문에서 찾을 수 없는 근거가 있습니다.'))
    return ordered, issues
