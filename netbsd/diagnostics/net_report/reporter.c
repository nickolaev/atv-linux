/* Report the NetBSD installer userland milestone over IPv4. */
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#define REPORT_PORT 8083
#define REPORT_LIMIT (64 * 1024)
#define REPORT_TIMEOUT 15

static const char commands[] =
    "iface=$1\n"
    "if [ \"$iface\" = rtk0 ] && ! /sbin/ifconfig rtk0 >/dev/null 2>&1 &&\n"
    "    /sbin/ifconfig re0 >/dev/null 2>&1; then\n"
    "    iface=re0\n"
    "fi\n"
    "/sbin/ifconfig \"$iface\" inet \"$2\" netmask \"$3\" up\n"
    "status=$?\n"
    "printf 'milestone=installer-profile\\nifconfig_status=%s\\n' \"$status\"\n"
    "printf 'interface=%s address=%s netmask=%s\\n' \"$iface\" \"$2\" \"$3\"\n"
    "/sbin/ifconfig \"$iface\"\n"
    "printf '%s\\n' '--- dmesg ---'\n"
    "/sbin/dmesg\n"
    "printf 'dmesg_status=%s\\nreport=complete\\n' \"$?\"\n";

static int
send_all(int socket_fd, const char *data, size_t length)
{
    while (length != 0) {
        ssize_t written = write(socket_fd, data, length);
        if (written <= 0)
            return -1;
        data += written;
        length -= (size_t)written;
    }
    return 0;
}

static int
connect_report(const struct sockaddr_in *destination)
{
    for (int attempt = 0; attempt < 5; attempt++) {
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0)
            break;
        if (connect(fd, (const struct sockaddr *)destination,
            sizeof(*destination)) == 0)
            return fd;
        int saved_errno = errno;
        close(fd);
        errno = saved_errno;
        if (attempt < 4)
            sleep(1);
    }
    return -1;
}

static int
report(int input_fd, const struct sockaddr_in *destination, const char *header)
{
    char chunk[4096];
    size_t remaining = REPORT_LIMIT;
    ssize_t length = read(input_fd, chunk, sizeof(chunk));
    if (length <= 0) {
        fprintf(stderr, "atv-net-report: no installer report\n");
        return 1;
    }

    int fd = connect_report(destination);
    if (fd < 0) {
        perror("atv-net-report: connect");
        return 1;
    }
    if (send_all(fd, header, strlen(header)) < 0)
        goto fail;
    while (length > 0 && remaining != 0) {
        size_t count = (size_t)length;
        if (count > remaining)
            count = remaining;
        if (send_all(fd, chunk, count) < 0)
            goto fail;
        remaining -= count;
        if (remaining == 0 && count < (size_t)length)
            break;
        length = read(input_fd, chunk, sizeof(chunk));
    }
    if (length < 0)
        goto fail;
    if (remaining == 0 && length > 0) {
        static const char marker[] = "\nreport=truncated\n";
        if (send_all(fd, marker, sizeof(marker) - 1) < 0)
            goto fail;
    }
    close(fd);
    return 0;

fail:
    perror("atv-net-report: transfer");
    close(fd);
    return 1;
}

int
main(void)
{
    static const char launch_id[] = ATV_REPORT_ID;
    static const char allowed[] =
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-";
    static const char header[] = "ATVNETBSD1 " ATV_REPORT_ID "\n";
    struct sockaddr_in destination = { 0 };
    struct in_addr local, netmask;
    int fds[2];

    if (sizeof(launch_id) < 2 || sizeof(launch_id) > 65 ||
        strspn(launch_id, allowed) != sizeof(launch_id) - 1 ||
        inet_pton(AF_INET, ATV_REPORT_HOST, &destination.sin_addr) != 1 ||
        inet_pton(AF_INET, ATV_REPORT_ADDR, &local) != 1 ||
        inet_pton(AF_INET, ATV_REPORT_NETMASK, &netmask) != 1) {
        fprintf(stderr, "atv-net-report: invalid build configuration\n");
        return 1;
    }
#ifdef __NetBSD__
    destination.sin_len = sizeof(destination);
#endif
    destination.sin_family = AF_INET;
    destination.sin_port = htons(REPORT_PORT);
    if (pipe(fds) < 0) {
        perror("atv-net-report: pipe");
        return 1;
    }
    alarm(REPORT_TIMEOUT);
    pid_t child = fork();
    if (child == 0) {
        close(fds[0]);
        if (dup2(fds[1], STDOUT_FILENO) < 0 ||
            dup2(fds[1], STDERR_FILENO) < 0)
            _exit(1);
        close(fds[1]);
        execl("/bin/sh", "sh", "-c", commands, "atv-net-report",
            ATV_REPORT_IF, ATV_REPORT_ADDR, ATV_REPORT_NETMASK, (char *)NULL);
        _exit(1);
    }
    close(fds[1]);
    if (child < 0) {
        perror("atv-net-report: fork");
        close(fds[0]);
        return 1;
    }
    signal(SIGPIPE, SIG_IGN);
    int status = report(fds[0], &destination, header);
    close(fds[0]);
    if (waitpid(child, NULL, 0) < 0)
        return 1;
    return status;
}
