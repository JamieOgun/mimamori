import { notFound } from "next/navigation";

import { fetchCall } from "../../../lib/api";
import { CallDetail } from "./call-detail";

export default async function CallDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const call = await fetchCall(id);

  if (!call) {
    notFound();
  }

  return <CallDetail call={call} />;
}
