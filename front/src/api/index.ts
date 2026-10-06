// VITE_USE_MOCK=true 이면 목업, 아니면 실제 백엔드. 화면 코드는 항상 이 파일을 거친다.
import { httpAgentApi } from './http/agentApi';
import { mockAgentApi } from './mock/agentApi';
import type { AgentApi } from './types';

export const USING_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

export const agentApi: AgentApi = USING_MOCK ? mockAgentApi : httpAgentApi;

export * from './types';
