from subprocess import check_output

docker_id_cmd = 'docker ps | grep python_podcast_production_postgres | cut -d " " -f 1'
postgres_id = (check_output(docker_id_cmd, shell=True)
               .decode('utf-8')
               .replace("\n", "")[:12])
print(postgres_id)

backup_cmd = 'docker-compose -f production.yml run postgres backup | cut -d " " -f 5'
backup_lines = (check_output(backup_cmd, shell=True)
               .decode('utf-8')
               .split("\n"))
backup_name = None
for line in backup_lines:
    if "backup" in line:
        # there are weird escape sequences in backup_name
        backup_name = "".join([c for c in line if c.isalnum() or c in set(['.', '_'])])
assert backup_name is not None
print(backup_name)

copy_cmd = 'docker cp {}:/backups/{} backups'.format(
    postgres_id, backup_name)
print(copy_cmd)
result = check_output(copy_cmd, shell=True)
print(result)

ssh_cmd = 'scp python-podcast:site/backups/{} backups'.format(backup_name)
print(ssh_cmd)
