package com.pms.common.config;

import java.time.Clock;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 시간은 항상 이 Clock 빈을 통해 읽는다.
 * 도메인·유스케이스에서 LocalDate.now()를 직접 부르면 테스트에서 시간을 고정할 수 없다.
 */
@Configuration
public class ClockConfig {

    @Bean
    public Clock clock() {
        return Clock.systemDefaultZone();
    }
}
