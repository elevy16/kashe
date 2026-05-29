export const ONBOARDING_STORAGE_KEY = 'hasSeenOnboarding';

export function hasSeenOnboarding() {
  return localStorage.getItem(ONBOARDING_STORAGE_KEY) === 'true';
}

export function markOnboardingComplete() {
  localStorage.setItem(ONBOARDING_STORAGE_KEY, 'true');
}

/** After authentication from login flows — always land on home. */
export function navigateAfterAuth(navigate) {
  navigate('/home');
}
