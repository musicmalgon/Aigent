import { apiFetch } from "./client";

// app/models/consent.py의 ConsentType과 1:1.
export type ConsentType =
  | "health_data"
  | "emotion_diary"
  | "terms_of_service"
  | "privacy_policy"
  | "external_integration";
export type ConsentStatus = "granted" | "withdrawn";

export interface ConsentRecord {
  id: string;
  user_id: string;
  consent_type: ConsentType;
  status: ConsentStatus;
  granted_at: string;
  withdrawn_at: string | null;
  source: string;
  created_at: string;
}

const SOURCE = "onboarding_consent_screen";

export async function grantConsent(consentType: ConsentType): Promise<ConsentRecord> {
  return apiFetch<ConsentRecord>("/api/v1/consents", {
    method: "POST",
    body: JSON.stringify({ consent_type: consentType, source: SOURCE }),
  });
}

export async function withdrawConsent(consentType: ConsentType): Promise<ConsentRecord> {
  return apiFetch<ConsentRecord>(`/api/v1/consents/${consentType}`, {
    method: "DELETE",
  });
}

export async function getCurrentConsents(): Promise<ConsentRecord[]> {
  return apiFetch<ConsentRecord[]>("/api/v1/consents");
}
