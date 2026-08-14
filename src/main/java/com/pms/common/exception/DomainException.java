package com.pms.common.exception;

import lombok.Getter;

/**
 * 모든 도메인 예외의 부모.
 * 도메인은 이 계층의 예외로만 실패를 표현하고, HTTP 변환은 GlobalExceptionHandler가 한다.
 */
@Getter
public abstract class DomainException extends RuntimeException {

    private final ErrorCode errorCode;

    protected DomainException(ErrorCode errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
    }
}
