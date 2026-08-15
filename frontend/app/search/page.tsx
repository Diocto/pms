// S1 객실 검색 — 본체는 T3에서 만든다. T1에서는 경로와 뼈대만 세운다.
export default function SearchPage() {
  return (
    <>
      <h1 className="h1">묵을 곳을 찾습니다</h1>
      <p className="sub">날짜와 인원을 넣으면 그 기간 내내 비어 있는 객실만 보여줍니다.</p>
      <div className="card card-pad">
        <p className="note">
          <span>·</span>
          <span>T3에서 구현 — 시안 S1 (상태 6종)</span>
        </p>
      </div>
    </>
  );
}
