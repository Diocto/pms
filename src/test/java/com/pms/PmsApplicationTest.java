package com.pms;

import static org.assertj.core.api.Assertions.assertThat;

import com.pms.support.IntegrationTestBase;
import javax.sql.DataSource;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * 하네스 검증용 스모크 테스트.
 * 애플리케이션 컨텍스트가 실제 MySQL·Redis 컨테이너 위에서 뜨는지 확인한다.
 */
class PmsApplicationTest extends IntegrationTestBase {

    @Autowired
    DataSource dataSource;

    @Autowired
    StringRedisTemplate redisTemplate;

    @Test
    @DisplayName("애플리케이션 컨텍스트가 MySQL과 함께 뜬다")
    void 컨텍스트가_MySQL과_함께_뜬다() throws Exception {
        try (var connection = dataSource.getConnection()) {
            assertThat(connection.isValid(3)).isTrue();
        }
    }

    @Test
    @DisplayName("Redis에 읽고 쓸 수 있다")
    void Redis에_읽고_쓸_수_있다() {
        redisTemplate.opsForValue().set("harness:smoke", "ok");

        assertThat(redisTemplate.opsForValue().get("harness:smoke")).isEqualTo("ok");
    }
}
