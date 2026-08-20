import type { LucideIcon } from "lucide-react";
import { Activity, BookOpen, ClipboardPenLine, Home, Target, UserRound } from "lucide-react";

export type AppScreen =
  | "welcome"
  | "signup"
  | "login"
  | "consent"
  | "mode"
  | "burnout"
  | "survey"
  | "result"
  | "burnoutResult"
  | "home"
  | "record"
  | "past"
  | "report"
  | "plan"
  | "profile";

export type OverlayKind =
  | "forgot"
  | "record"
  | "integration"
  | "consent-history"
  | "account"
  | "consent-detail"
  | null;

export type OnboardMode = "brief" | "detailed";

export type NavItem = { id: AppScreen; label: string; icon: LucideIcon };

export const nav: readonly NavItem[] = [
  { id: "home", label: "홈", icon: Home },
  { id: "record", label: "오늘 기록", icon: ClipboardPenLine },
  { id: "past", label: "지난 기록", icon: BookOpen },
  { id: "report", label: "생활 리포트", icon: Activity },
  { id: "plan", label: "회복 계획", icon: Target },
  { id: "profile", label: "마이페이지", icon: UserRound },
] as const;

export const EMOTION_DISPLAY_LABELS: Record<string, string> = {
  기쁨: "기쁨",
  불안: "불안",
  당황: "당황",
  분노: "분노",
  슬픔: "슬픔",
  상처: "무기력",
};

export const weekly = [42, 51, 45, 59, 63, 75, 69];

export const pastRecords = [
  {
    date: "7월 17일 목요일",
    summary: "잠드는 시간이 늦었지만, 오후에는 오래 쉬어갈 수 있었어요.",
    meta: "수면 5시간 40분 · 휴식 1시간 10분 · 무기력",
    emotion: "무기력",
  },
  {
    date: "7월 16일 수요일",
    summary: "해야 할 일이 많았지만, 저녁에는 잠시 걸었어요.",
    meta: "수면 6시간 10분 · 휴식 35분 · 지침",
    emotion: "지침",
  },
  {
    date: "7월 15일 화요일",
    summary: "평소와 비슷한 흐름으로 하루를 마무리했어요.",
    meta: "수면 7시간 5분 · 휴식 1시간 20분 · 괜찮음",
    emotion: "괜찮음",
  },
];
