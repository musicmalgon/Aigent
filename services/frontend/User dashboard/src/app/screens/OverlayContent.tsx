import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { Field, Integration, SummaryLine } from "../components/common";
import type { AppScreen, OverlayKind } from "../types";
import { getCurrentUser, updateUserName, updateUserPassword, deleteAccountData, type UserRead } from "../api/users";
import { logout } from "../api/auth";
import { getBehavioralRecordByDate, type BehavioralRecordRead } from "../api/behavioralRecords";
import { getEmotionAnalyses, type EmotionAnalysisRead } from "../api/emotionAnalyses";
import { getCurrentConsents, type ConsentRecord, type ConsentType } from "../api/consents";

// 화면에 보여줄 5개 항목 -> 백엔드 ConsentType 매핑 (Consent.tsx와 완전히 동일한 이름 사용 — "자세히" 상세 문구를 같이 찾아 쓰기 위함)
const CONSENT_ITEM_TYPE_MAP: Record<string, ConsentType> = {
  "건강·생활 데이터 활용 동의": "health_data",
  "생활 흐름 분석 활용 동의": "emotion_diary",
};

function formatConsentDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}. ${d.getMonth() + 1}. ${d.getDate()}`;
}

// TODO: 실제 법무 검토된 약관/정책 문구로 교체 필요. 지금은 화면 동작 확인용 임시 텍스트.
const CONSENT_DETAIL_CONTENT: Record<string, string> = {
  "서비스 이용약관":
    "Re:Mind 서비스 이용에 관한 기본 약관이에요. 서비스는 의료적 진단을 제공하지 않으며, 기록을 바탕으로 한 참고 정보만 제공해요. (실제 약관 전문은 법무 검토 후 교체 예정)",
  "개인정보 수집 및 이용":
    "회원가입, 서비스 제공을 위해 이메일 등 최소한의 개인정보를 수집해요. 수집한 정보는 서비스 제공 목적 외에는 사용하지 않아요. (실제 정책 전문은 법무 검토 후 교체 예정)",
  "건강·생활 데이터 활용 동의":
    "수면, 휴식, 공부·업무, 운동 시간 등 생활 기록 데이터를 분석해 생활 흐름 리포트를 만드는 데 활용해요.",
  "생활 흐름 분석 활용 동의":
    "남기신 하루 기록 텍스트를 바탕으로 감정 상태를 분석하는 데 활용해요. AI가 분석한 결과는 참고용이에요.",
  "선택적 외부 서비스 연동 동의":
    "Google 캘린더, 건강 앱 등 외부 서비스와 연동해 자동으로 기록을 채우는 데 활용해요. 연동하지 않아도 서비스 이용에는 문제 없어요.",
};

function formatMinutes(min: number | null): string {
  if (min === null) return "기록 없음";
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (h === 0) return `${m}분`;
  if (m === 0) return `${h}시간`;
  return `${h}시간 ${m}분`;
}

export function OverlayContent({
  kind,
  close,
  go,
  selectedDate,
  selectedConsentItem,
  onUserNameChange,
  onOpenConsentDetail,
}: {
  kind: OverlayKind;
  close: () => void;
  go: (screen: AppScreen) => void;
  selectedDate?: string;
  selectedConsentItem?: string | null;
  onUserNameChange?: (name: string) => void;
  onOpenConsentDetail?: (item: string) => void;
}) {
  const [sent, setSent] = useState(false);
  const [connected, setConnected] = useState(false);

  // --- record(지난 기록 상세) 전용 상태 ---
  const [recordData, setRecordData] = useState<BehavioralRecordRead | null>(null);
  const [recordEmotion, setRecordEmotion] = useState<EmotionAnalysisRead | null>(null);
  const [recordLoading, setRecordLoading] = useState(false);
  const [recordError, setRecordError] = useState<string | null>(null);

  // --- consent-history 전용 상태 ---
  const [consentRecords, setConsentRecords] = useState<ConsentRecord[]>([]);
  const [consentLoading, setConsentLoading] = useState(false);

  // --- account 전용 상태 ---
  const [accountUser, setAccountUser] = useState<UserRead | null>(null);
  const [accountLoading, setAccountLoading] = useState(false);
  const [editing, setEditing] = useState<"name" | "password" | "delete" | null>(null);

  const [nameInput, setNameInput] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [nameSaving, setNameSaving] = useState(false);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordSaved, setPasswordSaved] = useState(false);

  const [deletePassword, setDeletePassword] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (kind !== "record" || !selectedDate) return;
    let cancelled = false;
    setRecordLoading(true);
    setRecordError(null);
    (async () => {
      try {
        const record = await getBehavioralRecordByDate(selectedDate);
        if (cancelled) return;
        setRecordData(record);
        try {
          const analyses = await getEmotionAnalyses();
          if (!cancelled) {
            setRecordEmotion(analyses.find(a => a.record_date === selectedDate) ?? null);
          }
        } catch {
          // 감정분석 조회 실패는 치명적이지 않으니 생활기록만이라도 보여줌
        }
      } catch (err) {
        if (!cancelled) setRecordError(err instanceof Error ? err.message : "기록을 불러오지 못했습니다.");
      } finally {
        if (!cancelled) setRecordLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [kind, selectedDate]);

  useEffect(() => {
    if (kind !== "consent-history") return;
    let cancelled = false;
    setConsentLoading(true);
    (async () => {
      try {
        const records = await getCurrentConsents();
        if (!cancelled) setConsentRecords(records);
      } catch {
        // 무시 — 아래에서 항목별로 "기록 없음"으로 표시됨
      } finally {
        if (!cancelled) setConsentLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [kind]);

  useEffect(() => {
    if (kind !== "account") return;
    let cancelled = false;
    setAccountLoading(true);
    (async () => {
      try {
        const user = await getCurrentUser();
        if (!cancelled) {
          setAccountUser(user);
          setNameInput(user.name);
        }
      } catch {
        // 무시 — 아래에서 "현재 이름" 자리에 빈 값으로 표시됨
      } finally {
        if (!cancelled) setAccountLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [kind]);

  async function handleSaveName() {
    setNameError(null);
    if (nameInput.trim().length === 0) {
      setNameError("이름을 입력해 주세요.");
      return;
    }
    setNameSaving(true);
    try {
      const updated = await updateUserName(nameInput.trim());
      setAccountUser(updated);
      onUserNameChange?.(updated.name);
      setEditing(null);
    } catch (err) {
      setNameError(err instanceof Error ? err.message : "이름 변경 중 오류가 발생했습니다.");
    } finally {
      setNameSaving(false);
    }
  }

  async function handleSavePassword() {
    setPasswordError(null);
    setPasswordSaved(false);
    if (currentPassword.length === 0 || newPassword.length === 0) {
      setPasswordError("현재 비밀번호와 새 비밀번호를 모두 입력해 주세요.");
      return;
    }
    setPasswordSaving(true);
    try {
      await updateUserPassword(currentPassword, newPassword);
      setPasswordSaved(true);
      setCurrentPassword("");
      setNewPassword("");
      setEditing(null);
    } catch (err) {
      setPasswordError(err instanceof Error ? err.message : "비밀번호 변경 중 오류가 발생했습니다.");
    } finally {
      setPasswordSaving(false);
    }
  }

  async function handleDeleteAccount() {
    setDeleteError(null);
    if (deletePassword.length === 0) {
      setDeleteError("비밀번호를 입력해 주세요.");
      return;
    }
    setDeleting(true);
    try {
      await deleteAccountData(deletePassword);
      logout();
      close();
      go("welcome");
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "계정 삭제 중 오류가 발생했습니다.");
    } finally {
      setDeleting(false);
    }
  }

  if (kind === "forgot")
    return (
      <>
        <p className="text-sm leading-6 text-muted-foreground">가입할 때 사용한 이메일을 입력하면 비밀번호를 다시 설정할 수 있는 안내를 보내드려요.</p>
        {sent ? (
          <p className="mt-7 font-serif text-lg leading-8">입력한 이메일로 비밀번호를 다시 설정할 수 있는 안내를 보냈어요.</p>
        ) : (
          <>
            <Field label="이메일" placeholder="name@example.com" type="email" />
            <button onClick={() => setSent(true)} className="mt-7 rounded-lg bg-[#68796b] px-4 py-2.5 text-sm font-semibold text-white">
              안내 보내기
            </button>
          </>
        )}
      </>
    );

  if (kind === "record") {
    if (recordLoading) return <p className="text-sm text-muted-foreground">불러오는 중...</p>;
    if (recordError) return <p className="text-sm text-red-500">{recordError}</p>;
    if (!recordData) return <p className="text-sm text-muted-foreground">이 날짜의 기록을 찾을 수 없어요.</p>;

    return (
      <>
        <p className="text-xs text-muted-foreground">{selectedDate}</p>
        <div className="mt-6 divide-y divide-border border-y border-border">
          <SummaryLine label="수면" value={formatMinutes(recordData.sleep_minutes)} />
          <SummaryLine label="휴식" value={formatMinutes(recordData.rest_minutes)} />
          <SummaryLine label="공부 · 업무" value={formatMinutes(recordData.work_or_study_minutes)} />
          <SummaryLine label="운동" value={formatMinutes(recordData.exercise_minutes)} />
          <SummaryLine label="오늘의 마음" value={recordEmotion?.emotion ?? "분석된 기록 없음"} />
        </div>
        <button
          onClick={() => {
            close();
            go("record");
          }}
          className="mt-7 text-sm text-[#536458] underline underline-offset-4"
        >
          오늘 기록 남기러 가기
        </button>
      </>
    );
  }

  if (kind === "integration")
    return (
      <>
        <p className="text-sm leading-6 text-muted-foreground">연동된 기록도 직접 수정한 값이 우선해요.</p>
        <Integration name="Google Calendar" detail="일정 개수와 바쁜 시간대를 기록에 참고해요." connected={connected} setConnected={setConnected} />
        {/* Health Connect(삼성헬스 등)는 브라우저에서 접근 불가능한 안드로이드
            전용 API라 이 웹 화면에서 누른다고 연결되는 구조가 아니다. 실제
            연동은 모바일 앱의 권한 허용으로 이미 자동으로 이뤄지고 있어서
            (SyncWorker, #37/#109) Google Calendar와 같은 "연결하기" 토글
            대신 상태를 정확히 안내하는 문구만 보여준다. */}
        <div className="border-b border-border py-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium">Samsung Health</p>
              <p className="mt-1 max-w-xs text-xs leading-5 text-muted-foreground">수면과 활동 기록을 오늘 기록에 가져와요.</p>
            </div>
            <span className="rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground">모바일 앱에서 연동</span>
          </div>
          <p className="mt-3 text-[11px] text-muted-foreground">
            이 웹 화면에서는 연결할 수 없어요 — 리마인드 모바일 앱에서 Health Connect 권한을 허용하면 자동으로 동기화돼요.
          </p>
        </div>
        <p className="mt-6 text-xs leading-5 text-muted-foreground">Google Calendar 연동은 아직 준비 중이에요. 현재 화면에서는 연결 흐름만 미리 볼 수 있어요.</p>
      </>
    );

  if (kind === "consent-history") {
    if (consentLoading) return <p className="text-sm text-muted-foreground">불러오는 중...</p>;
    return (
      <div className="divide-y divide-border border-y border-border">
        {(
          [
            ["서비스 이용약관", "필수"],
            ["개인정보 수집 및 이용", "필수"],
            ["건강·생활 데이터 활용 동의", "필수"],
            ["생활 흐름 분석 활용 동의", "필수"],
            ["선택적 외부 서비스 연동 동의", "선택"],
          ] as const
        ).map(([x, requiredLabel]) => {
          const consentType = CONSENT_ITEM_TYPE_MAP[x];
          const record = consentType ? consentRecords.find(r => r.consent_type === consentType) : undefined;
          const statusLabel = consentType
            ? record?.status === "granted"
              ? `${requiredLabel} · ${formatConsentDate(record.granted_at)}`
              : `${requiredLabel} · 동의 안 함`
            : `${requiredLabel} · 가입 시 동의`;
          return (
            <div className="flex items-center justify-between gap-4 py-4" key={x}>
              <div>
                <p className="text-sm">{x}</p>
                <p className="mt-1 text-xs text-muted-foreground">{statusLabel}</p>
              </div>
              <button onClick={() => onOpenConsentDetail?.(x)} className="text-xs text-[#536458] underline underline-offset-4">자세히</button>
            </div>
          );
        })}
      </div>
    );
  }

  if (kind === "account") {
    if (accountLoading) {
      return <p className="text-sm text-muted-foreground">불러오는 중...</p>;
    }
    return (
      <>
        <div className="divide-y divide-border border-y border-border">
          {/* 이름 변경 */}
          <div className="py-5">
            <button onClick={() => setEditing(editing === "name" ? null : "name")} className="flex w-full items-center justify-between text-left">
              <span>
                <strong className="block text-sm font-medium">이름 변경</strong>
                <span className="mt-1 block text-xs text-muted-foreground">현재 이름 · {accountUser?.name || "-"}</span>
              </span>
              <ChevronRight size={16} className={editing === "name" ? "rotate-90 transition-transform" : "transition-transform"} />
            </button>
            {editing === "name" && (
              <div className="mt-4">
                <Field label="새 이름" placeholder="이름을 입력해 주세요" value={nameInput} onChange={e => setNameInput(e.target.value)} />
                {nameError && <p className="mt-2 text-xs text-red-500">{nameError}</p>}
                <button
                  onClick={handleSaveName}
                  disabled={nameSaving}
                  className="mt-4 rounded-lg bg-[#68796b] px-4 py-2 text-xs font-semibold text-white disabled:opacity-60"
                >
                  {nameSaving ? "저장 중..." : "저장하기"}
                </button>
              </div>
            )}
          </div>

          {/* 비밀번호 변경 */}
          <div className="py-5">
            <button onClick={() => setEditing(editing === "password" ? null : "password")} className="flex w-full items-center justify-between text-left">
              <span>
                <strong className="block text-sm font-medium">비밀번호 변경</strong>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {passwordSaved ? "방금 변경됐어요" : "안전하게 계정을 관리해요."}
                </span>
              </span>
              <ChevronRight size={16} className={editing === "password" ? "rotate-90 transition-transform" : "transition-transform"} />
            </button>
            {editing === "password" && (
              <div className="mt-4 space-y-3">
                <Field label="현재 비밀번호" type="password" placeholder="현재 비밀번호" value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} />
                <Field label="새 비밀번호" type="password" placeholder="8자 이상" value={newPassword} onChange={e => setNewPassword(e.target.value)} />
                {passwordError && <p className="mt-2 text-xs text-red-500">{passwordError}</p>}
                <button
                  onClick={handleSavePassword}
                  disabled={passwordSaving}
                  className="mt-2 rounded-lg bg-[#68796b] px-4 py-2 text-xs font-semibold text-white disabled:opacity-60"
                >
                  {passwordSaving ? "저장 중..." : "변경하기"}
                </button>
              </div>
            )}
          </div>

          {/* 계정 연결 — 실제 연동 기능은 준비 중이라 UI만 유지 */}
          <button className="flex w-full items-center justify-between py-5 text-left">
            <span>
              <strong className="block text-sm font-medium">계정 연결</strong>
              <span className="mt-1 block text-xs text-muted-foreground">Google · 연결 안 됨</span>
            </span>
            <ChevronRight size={16} />
          </button>

          {/* 계정 삭제와 달리 되돌리는 데 확인 절차가 필요 없어서 바로 실행함 */}
          <button
            onClick={() => {
              logout();
              close();
              go("welcome");
            }}
            className="flex w-full items-center justify-between py-5 text-left"
          >
            <span>
              <strong className="block text-sm font-medium">로그아웃</strong>
              <span className="mt-1 block text-xs text-muted-foreground">다시 로그인하면 이어서 기록할 수 있어요.</span>
            </span>
            <ChevronRight size={16} />
          </button>
        </div>

        <div className="mt-10 border-t border-border pt-5">
          <p className="text-sm text-[#8d5541]">계정 삭제</p>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">계정을 삭제하면 지금까지의 기록과 연결 정보도 함께 사라져요.</p>
          {editing !== "delete" ? (
            <button onClick={() => setEditing("delete")} className="mt-4 text-xs text-[#8d5541] underline underline-offset-4">
              삭제 방법 확인하기
            </button>
          ) : (
            <div className="mt-4">
              <Field label="비밀번호 확인" type="password" placeholder="현재 비밀번호" value={deletePassword} onChange={e => setDeletePassword(e.target.value)} />
              {deleteError && <p className="mt-2 text-xs text-red-500">{deleteError}</p>}
              <button
                onClick={handleDeleteAccount}
                disabled={deleting}
                className="mt-4 rounded-lg bg-[#8d5541] px-4 py-2 text-xs font-semibold text-white disabled:opacity-60"
              >
                {deleting ? "삭제 중..." : "정말 삭제하기"}
              </button>
            </div>
          )}
        </div>
      </>
    );
  }

  if (kind === "consent-detail") {
    const content = selectedConsentItem ? CONSENT_DETAIL_CONTENT[selectedConsentItem] : null;
    return (
      <>
        {onOpenConsentDetail && (
          <button
            onClick={() => onOpenConsentDetail("__back_to_history__")}
            className="mb-4 text-xs text-muted-foreground underline underline-offset-4"
          >
            ← 동의내역으로
          </button>
        )}
        {selectedConsentItem && <h3 className="font-serif text-lg leading-8">{selectedConsentItem}</h3>}
        <p className="mt-4 text-sm leading-7 text-muted-foreground">
          {content ?? "이 항목의 내용을 확인할 수 있어요. 동의 범위는 언제든 마이페이지에서 다시 살펴볼 수 있어요."}
        </p>
      </>
    );
  }

  return <p className="text-sm text-muted-foreground">이 항목의 내용을 확인할 수 있어요. 동의 범위는 언제든 마이페이지에서 다시 살펴볼 수 있어요.</p>;
}