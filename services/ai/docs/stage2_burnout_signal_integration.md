# Stage 2 멀티라벨 실사용 연동

Stage 2 모델은 기존 6분류 감정 모델을 대체하지 않는다. 한 입력에서
`exhaustion`, `overload`, `helplessness`, `low_efficacy`, `anxiety`,
`irritability`가 동시에 나타날 수 있는 별도 sigmoid 모델이다.

## 활성화

학습 결과 폴더에 `model/`, `tokenizer/`, `thresholds.json`,
`label_mapping.json`, `run_config.json`이 모두 생성된 뒤 AI 서비스 환경에 다음을
설정한다.

```dotenv
BURNOUT_SIGNALS_ENABLED=true
BURNOUT_SIGNALS_ARTIFACT_DIR=C:\Users\lee\workspace\rewind\Aigent-integration-audit\services\ai\data\outputs\stage2-burnout-multilabel-v1
BURNOUT_SIGNALS_DEVICE=auto
BURNOUT_SIGNALS_MAX_LENGTH=256
```

아티팩트의 라벨 순서, 멀티라벨 task type, max length, 임계값 파일 중 하나라도
계약과 다르면 모델은 로드되지 않는다. 이 실패는 기존 감정 분류 서비스의
readiness에는 영향을 주지 않는다.

## 호출 경로

- AI 내부 API: `POST /v1/burnout-signals/analyze`
- Backend 사용자 API: `POST /api/v1/emotion-analyses/burnout-signals/analyze`
- 요청 본문: 기존 감정 분석과 같은 `hs01`, `hs02`, 선택 `hs03`
- Backend 경로는 감정 일기 동의를 요구한다.

응답의 여섯 확률은 서로 독립적이므로 합이 1일 필요가 없다. 라벨별 독립 검증을
통과한 항목만 `present` 또는 `absent`가 되고, 통과하지 못한 항목은
`unvalidated`로 반환된다. `active_signals`에는 검증된 `present` 항목만 들어간다.

## 제품 표시 원칙

내부 라벨은 화면에서 다음처럼 비진단적 표현으로 표시한다.

| 내부 라벨 | 권장 표시 |
|---|---|
| `exhaustion` | 에너지 소진 패턴 |
| `overload` | 부담이 몰린 패턴 |
| `helplessness` | 통제하기 어렵게 느낀 패턴 |
| `low_efficacy` | 해낸 느낌이 낮은 패턴 |
| `anxiety` | 걱정과 긴장이 이어진 패턴 |
| `irritability` | 예민함이 높아진 패턴 |

- `unvalidated` 항목과 원시 확률은 사용자 화면에 노출하지 않는다.
- "번아웃 진단", "위험 확률" 같은 표현을 사용하지 않는다.
- 결과는 현재 저장하지 않으며 기존 위험점수 입력에도 사용하지 않는다.
- 모든 응답은 `informational_only=true`, `risk_score_eligible=false`다.
- 현재 100건은 임계값 조정에도 사용되므로 독립 최종 테스트셋이 추가되기 전까지
  모델 전체를 의료·위험 판단에 사용하지 않는다.

## 단계적 출시

1. `shadow_only`: 응답 검증과 로그 집계만 하며 사용자에게 표시하지 않는다.
2. `partial`: 검증 통과 라벨만 정보 카드 후보로 사용할 수 있다.
3. `validated`: 여섯 라벨이 모두 기준을 통과했음을 뜻하지만, 위험점수 연계 권한은
   아니다. 별도 최종 평가와 제품 정책 승인 전까지 정보 제공 전용을 유지한다.
