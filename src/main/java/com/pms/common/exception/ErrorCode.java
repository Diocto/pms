package com.pms.common.exception;

import lombok.Getter;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;

/**
 * 에러 코드와 HTTP 상태의 매핑.
 * feature가 추가될 때 여기에 코드를 추가한다. 이 파일은 공유 파일이므로
 * 수정 시 docs/architecture/parallel-work.md의 공유 파일 절차를 따른다.
 */
@Getter
@RequiredArgsConstructor
public enum ErrorCode {

    // 공통
    INVALID_REQUEST(HttpStatus.BAD_REQUEST),
    RESOURCE_NOT_FOUND(HttpStatus.NOT_FOUND),
    INTERNAL_ERROR(HttpStatus.INTERNAL_SERVER_ERROR),

    // 상태 전이
    INVALID_STATE_TRANSITION(HttpStatus.CONFLICT),

    // 재고
    INSUFFICIENT_INVENTORY(HttpStatus.CONFLICT),

    // 멱등성
    DUPLICATE_REQUEST(HttpStatus.CONFLICT),
    REQUEST_IN_PROGRESS(HttpStatus.CONFLICT),

    // 락
    LOCK_ACQUISITION_FAILED(HttpStatus.SERVICE_UNAVAILABLE);

    private final HttpStatus status;
}
