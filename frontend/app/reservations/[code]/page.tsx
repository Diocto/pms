// S3 예약 상세 — 본체는 T5에서 만든다. T1에서는 경로와 뼈대만 세운다.
export default async function ReservationDetailPage({
  params,
}: {
  params: Promise<{ code: string }>;
}) {
  const { code } = await params;
  return (
    <>
      <h1 className="h1">예약 상세</h1>
      <p className="sub mono">{decodeURIComponent(code)}</p>
      <div className="card card-pad">
        <p className="note">
          <span>·</span>
          <span>T5에서 구현 — 시안 S3 (상태 6종 · 카운트다운)</span>
        </p>
      </div>
    </>
  );
}
