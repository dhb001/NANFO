export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface AccessToken {
  access_token: string;
  expires_in: number;
}

export interface UserProfile {
  user_id: string;
  email: string;
  display_name: string | null;
  roles: string[];
  permissions: string[];
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RefreshRequest {
  refresh_token: string;
}
