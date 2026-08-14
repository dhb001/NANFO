import http from 'k6/http';
import { check, sleep } from 'k6';

const baseUrl = __ENV.NANFO_BASE_URL || 'http://127.0.0.1:8000';
const authToken = __ENV.NANFO_AUTH_TOKEN || '';
const expectedStatusWhenAuth = Number(__ENV.VS17_EXPECTED_AUTH_STATUS || 200);
const vus = Number(__ENV.VS17_VUS || 5);
const duration = __ENV.VS17_DURATION || '20s';
const sleepSeconds = Number(__ENV.VS17_SLEEP_SECONDS || 0.2);

const headers = authToken
  ? { Authorization: `Bearer ${authToken}` }
  : {};
const expectedStatuses = authToken
  ? [expectedStatusWhenAuth]
  : [401, 403];

http.setResponseCallback(http.expectedStatuses(...expectedStatuses));

export const options = {
  vus,
  duration,
  discardResponseBodies: true,
  thresholds: {
    http_req_failed: ['rate<0.10'],
    http_req_duration: ['p(95)<1500'],
  },
};

function hasExpectedStatus(status) {
  if (authToken) {
    return status === expectedStatusWhenAuth;
  }
  return status === 401 || status === 403;
}

export default function () {
  const response = http.get(`${baseUrl}/api/v1/telemetry/health`, { headers });

  check(response, {
    'status is expected': (res) => hasExpectedStatus(res.status),
  });

  sleep(sleepSeconds);
}
