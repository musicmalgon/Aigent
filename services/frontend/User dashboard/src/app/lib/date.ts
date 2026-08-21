// 서비스가 한국 사용자 전용이라 "오늘/어제" 날짜를 KST 고정으로 계산한다.
// 예전엔 화면마다 각자 toISOString()(UTC)로 날짜를 만들면서 behavioral-records
// 요청의 time_zone 필드만 별도로(브라우저 로케일 기준) 채워 보냈는데, 그
// 둘이 서로 다른 기준이라 자정~오전 9시(KST) 사이엔 오늘 남긴 기록이 조용히
// "어제" 날짜로 저장됐다(#H7). 모바일(DailyRecordSync.kt, #143)은 이미 KST
// 고정이라 웹도 여기로 맞춰야 두 플랫폼이 같은 날짜를 보게 된다(#M1).
//
// App.tsx와 RecordView.tsx가 각자 같은 로직을 따로 들고 있다가 어긋난 게
// 이 버그의 근본 원인이었어서, 하나로 합쳐 재사용한다.
export const APP_TIME_ZONE = "Asia/Seoul";

function dateStringInTimeZone(date: Date, timeZone: string): string {
  // en-CA 로케일은 YYYY-MM-DD 형식을 그대로 반환해서 별도 조합이 필요 없다.
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

export function todayDateString(): string {
  return dateStringInTimeZone(new Date(), APP_TIME_ZONE);
}

// 24시간을 밀리초로 그냥 빼는 방식으로 계산한다(로컬 타임존의
// setDate(getDate()-1)이 아니라) -- 한국은 DST가 없어서 하루가 항상 정확히
// 24시간이고, Date.now() 기준 뺄셈은 실행 환경의 로컬 타임존 설정과 무관하게
// 항상 같은 결과를 준다.
export function yesterdayDateString(): string {
  const oneDayMs = 24 * 60 * 60 * 1000;
  return dateStringInTimeZone(new Date(Date.now() - oneDayMs), APP_TIME_ZONE);
}
