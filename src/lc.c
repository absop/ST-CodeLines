#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <errno.h>

#ifndef _WIN32
    #include <unistd.h>
#endif

#ifndef O_BINARY
    #define O_BINARY 0
#endif

#define IO_BUF_SIZE 8192

static char buffer[IO_BUF_SIZE] = {EOF};
static char *bufend = &buffer[IO_BUF_SIZE];
static char *bufptr = &buffer[2];
static char last;

static char peek() { return *bufptr++; }
static void flush_buffer(int fd)
{
    last = bufptr[-2];
    int len = read(fd, buffer, IO_BUF_SIZE - 1);
    if (len < 0) len = 0;
    buffer[len] = EOF;
    bufptr = buffer;
}

int lines_count(const char *filename)
{
    char ch;
    int nlines = 0;
    int fd = open(filename, O_RDONLY | O_BINARY);
    if (fd < 0) {
        fprintf(stderr, "Can not open file: %s, %s\n",
                filename, strerror(errno));
        return 0;
    }

    flush_buffer(fd);
    for (; ;) {
        ch = peek();
        switch (ch) {
            case '\n':
                ++nlines;
                break;

            case EOF:
                if (bufptr < bufend) {
                    close(fd);
                    if (bufptr >= &buffer[2]) {
                        last = bufptr[-2];
                    }
                    return nlines + (last != EOF && last != '\n');
                }
                flush_buffer(fd);
                break;

            default:
                break;
        }
    }
}

#ifndef BUILD_SHARED_OBJECT
int main()
{
    printf("%d\n", lines_count("lc.c"));            // 71
    printf("%d\n", lines_count("test/12.txt"));     // 12
    printf("%d\n", lines_count("test/12345.txt"));  // 12345

    return 0;
}
#endif
