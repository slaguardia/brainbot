import type { PageServerLoad } from './$types';
import { adminMetrics } from '$lib/server/admin';

export const load: PageServerLoad = async () => {
  return await adminMetrics();
};
