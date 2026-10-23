-- 로컬 전용(docker-compose.yml): 앱 사용자가 pytest DB(test_metrics)를 만들 수 있게 한다.
-- 운영 계정은 조율자가 HeatWave에 만든다.
GRANT ALL PRIVILEGES ON `test\_metrics%`.* TO 'metrics'@'%';
