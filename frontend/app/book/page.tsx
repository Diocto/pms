// S2 예약 주문서 — 본체는 T4에서 만든다. T1에서는 경로와 뼈대만 세운다.
export default function BookPage() {
  return (
    <>
      <h1 className="h1">예약 내용을 확인해 주세요</h1>
      <p className="sub">아직 방이 잡히지 않았습니다. 예약 버튼을 눌러야 객실이 확보됩니다.</p>
      <div className="card card-pad">
        <p className="note">
          <span>·</span>
          <span>T4에서 구현 — 시안 S2 (멱등성 키 · 409 4단계)</span>
        </p>
      </div>
    </>
  );
}
