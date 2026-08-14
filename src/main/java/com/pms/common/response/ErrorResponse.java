package com.pms.common.response;

import com.pms.common.exception.ErrorCode;

/**
 * 모든 에러 응답의 단일 형식. 스택 트레이스는 절대 담지 않는다.
 */
public record ErrorResponse(String code, String message) {

    public static ErrorResponse of(ErrorCode errorCode, String message) {
        return new ErrorResponse(errorCode.name(), message);
    }
}
