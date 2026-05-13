import type { PageServerLoad } from './$types';
import { getEntity } from '$lib/server/graphiti';

export const load: PageServerLoad = async ({ params }) => {
  const entity = await getEntity(params.id);
  return { entity };
};
