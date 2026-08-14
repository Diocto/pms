package com.pms.support;

import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Testcontainers;

/**
 * 통합 테스트의 공통 부모. 실제 MySQL과 Redis 컨테이너를 띄운다.
 *
 * H2를 쓰지 않는 이유: 락 동작(FOR UPDATE 대기, 갭락, 데드락 감지)이 실제 DB와 달라
 * 동시성 테스트가 아무것도 증명하지 못한다. docs/architecture/tdd.md 참고.
 *
 * 컨테이너는 static이라 JVM 하나에서 공유된다. 테스트 간 데이터 격리는 각 테스트가 책임진다.
 * 동시성 테스트는 @Transactional 롤백을 쓸 수 없으므로(스레드마다 별도 트랜잭션) 테이블을 직접 비운다.
 */
@SpringBootTest
@Testcontainers
public abstract class IntegrationTestBase {

    @ServiceConnection
    static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4")
        .withCommand("--character-set-server=utf8mb4",
                     "--collation-server=utf8mb4_unicode_ci",
                     "--transaction-isolation=REPEATABLE-READ");

    static final GenericContainer<?> REDIS = new GenericContainer<>("redis:7.4-alpine")
        .withExposedPorts(6379);

    static {
        // @Container 대신 직접 시작해 테스트 클래스 간에 컨테이너를 재사용한다
        MYSQL.start();
        REDIS.start();
    }

    @DynamicPropertySource
    static void redisProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.data.redis.host", REDIS::getHost);
        registry.add("spring.data.redis.port", () -> REDIS.getMappedPort(6379));
    }
}
