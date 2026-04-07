// src/app/dashboard/[projectId]/page.tsx
import DashboardClient from '@/DashboardClient';

export default async function DashboardPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return <DashboardClient projectId={projectId} />;
}