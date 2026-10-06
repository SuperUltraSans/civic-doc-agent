// 사는 지역, 나이대 (ilgeo.v1.profile). 서버에 저장하지 않고 요청마다 보낸다 (Memory).
import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react';
import type { UserProfile } from '../api/types';
import { useLocalStorage } from '../hooks/useLocalStorage';
import { STORAGE_KEYS } from '../lib/storage';

function parseProfile(raw: unknown): UserProfile | undefined {
  if (typeof raw !== 'object' || raw === null) return undefined;
  const r = raw as Record<string, unknown>;
  const profile: UserProfile = {};
  if (typeof r.region === 'string' && r.region.trim()) profile.region = r.region.trim().slice(0, 20);
  if (r.ageGroup === '60s' || r.ageGroup === '70s' || r.ageGroup === '80plus') profile.ageGroup = r.ageGroup;
  return profile;
}

interface ProfileValue {
  profile: UserProfile;
  setField(field: keyof UserProfile, value: string | null): void;
  clear(): void;
}

const ProfileContext = createContext<ProfileValue | null>(null);

export function ProfileProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useLocalStorage<UserProfile>(STORAGE_KEYS.profile, {}, parseProfile);

  const setField = useCallback(
    (field: keyof UserProfile, value: string | null) =>
      setProfile((p) => {
        const next = { ...p };
        if (value === null) delete next[field];
        else if (field === 'region') next.region = value.slice(0, 20);
        else if (value === '60s' || value === '70s' || value === '80plus') next.ageGroup = value;
        return next;
      }),
    [setProfile],
  );
  const clear = useCallback(() => setProfile({}), [setProfile]);

  const value = useMemo(() => ({ profile, setField, clear }), [profile, setField, clear]);
  return <ProfileContext.Provider value={value}>{children}</ProfileContext.Provider>;
}

export function useProfile(): ProfileValue {
  const ctx = useContext(ProfileContext);
  if (!ctx) throw new Error('ProfileProvider 가 필요해요');
  return ctx;
}
