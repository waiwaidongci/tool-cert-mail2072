import {request, saveFile} from '../api/http.js';
import {session} from './session.js';

const call = (path, body) => request(path, {token:session.token, body});
export const workspace = {
  spec: null,
  datasets: [],
  runs: [],
  comparisons: [],
  async init() { this.spec = await request('/spec'); },
  async refresh() {
    [this.datasets, this.runs, this.comparisons] =
      await Promise.all([call('/datasets'), call('/runs'), call('/comparisons')]);
  },
  getDataset: (id, offset = 0) => call(`/datasets/${id}?offset=${offset}`),
  getRun: id => call(`/runs/${id}`),
  upload: data => call('/datasets', data),
  start: data => call('/runs', data),
  review: (id, data) => call(`/runs/${id}/review`, data),
  audit: () => call('/audit'),
  schedules: () => call('/schedules'),
  deliveries: () => call('/deliveries'),
  schedule: data => call('/schedules', data),
  disable: id => call(`/schedules/${id}/disable`, {}),
  comparisons: () => call('/comparisons'),
  comparison: id => call(`/comparisons/${id}`),
  comparisonShifts: (id, asset) => call(`/comparisons/${id}/shifts${asset ? `?asset=${encodeURIComponent(asset)}` : ''}`),
  comparisonJobs: () => call('/comparisons/jobs'),
  startComparison: data => call('/comparisons', data),
  backfill: id => call(`/comparisons/${id}/backfill`, {}),
  download: (path, filename) => saveFile(path, session.token, filename),
};
