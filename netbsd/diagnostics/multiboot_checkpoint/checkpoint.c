/* RTL8139 transmit-only checkpoint at the NetBSD Multiboot 1 entry. */
#include <stdint.h>

#ifndef ATV_DST_PORT
#define ATV_DST_PORT 8084
#endif

enum {
    PCI_ADDRESS = 0xcf8,
    PCI_DATA = 0xcfc,
    PCI_COMMAND = 4,
    PCI_BAR0 = 0x10,
    PCI_IO = 1,
    PCI_MASTER = 4,

    RTL_IDR0 = 0x00,
    RTL_TSD0 = 0x10,
    RTL_TSAD0 = 0x20,
    RTL_COMMAND = 0x37,
    RTL_IMR = 0x3c,
    RTL_ISR = 0x3e,
    RTL_TCR = 0x40,
    RTL_MEDIA_STATUS = 0x58,
    RTL_HLTCLK = 0x5b,
    RTL_RESET = 0x10,
    RTL_RX_ENABLE = 0x08,
    RTL_TX_ENABLE = 0x04,
    RTL_LINK_DOWN = 0x04,
    RTL_TX_OK = 0x8000,
    RTL_TX_ABORTED = 0x40000000,
    RTL_TX_IFG96 = 3 << 24,
    RTL_TX_DMA_1024 = 6 << 8,
    RTL_TX_THRESHOLD_256 = 8 << 16,
    RESET_POLLS = 1 << 17,
    LINK_POLLS = 1 << 21,
    TX_POLLS = 1 << 19,

    ETHERNET_HEADER = 14,
    ETHERNET_MINIMUM = 60,
    IPV4_HEADER = 20,
    UDP_HEADER = 8,
};

static const uint8_t dst_mac[] = { ATV_DST_MAC };
static const uint8_t src_ip[] = { ATV_SRC_IP };
static const uint8_t dst_ip[] = { ATV_DST_IP };
static const char checkpoint_id[] = ATV_CHECKPOINT_ID;

_Static_assert(ATV_PCI_BUS >= 0 && ATV_PCI_BUS <= 255, "invalid PCI bus");
_Static_assert(ATV_PCI_DEV >= 0 && ATV_PCI_DEV <= 31, "invalid PCI device");
_Static_assert(ATV_PCI_FN >= 0 && ATV_PCI_FN <= 7, "invalid PCI function");
_Static_assert(ATV_DST_PORT > 0 && ATV_DST_PORT <= 65535, "invalid UDP port");
_Static_assert(sizeof(dst_mac) == 6 && sizeof(src_ip) == 4 && sizeof(dst_ip) == 4,
    "invalid Ethernet or IPv4 address");
_Static_assert(sizeof(checkpoint_id) > 1 && sizeof(checkpoint_id) <= 65,
    "invalid checkpoint ID length");

/* Paging is off and the linker places this DMA buffer in identity-mapped RAM. */
static uint8_t frame[160] __attribute__((aligned(16)));

static uint8_t in8(uint16_t port)
{
    uint8_t value;
    __asm__ volatile("inb %w1, %0" : "=a"(value) : "Nd"(port) : "memory");
    return value;
}

static uint16_t in16(uint16_t port)
{
    uint16_t value;
    __asm__ volatile("inw %w1, %0" : "=a"(value) : "Nd"(port) : "memory");
    return value;
}

static uint32_t in32(uint16_t port)
{
    uint32_t value;
    __asm__ volatile("inl %w1, %0" : "=a"(value) : "Nd"(port) : "memory");
    return value;
}

static void out8(uint16_t port, uint8_t value)
{
    __asm__ volatile("outb %0, %w1" : : "a"(value), "Nd"(port) : "memory");
}

static void out16(uint16_t port, uint16_t value)
{
    __asm__ volatile("outw %0, %w1" : : "a"(value), "Nd"(port) : "memory");
}

static void out32(uint16_t port, uint32_t value)
{
    __asm__ volatile("outl %0, %w1" : : "a"(value), "Nd"(port) : "memory");
}

static void pci_select(uint8_t reg)
{
    const uint32_t bdf = ((uint32_t)ATV_PCI_BUS << 16) |
        ((uint32_t)ATV_PCI_DEV << 11) | ((uint32_t)ATV_PCI_FN << 8);
    out32(PCI_ADDRESS, 0x80000000u | bdf | reg);
}

static void pci_write_command(uint16_t command)
{
    pci_select(PCI_COMMAND);
    /* The neighbouring PCI status register contains write-one-to-clear bits. */
    out16(PCI_DATA, command);
}

static void put16(uint8_t *p, uint16_t value)
{
    p[0] = value >> 8;
    p[1] = value;
}

static uint8_t *append_text(uint8_t *out, const char *text)
{
    while (*text != '\0')
        *out++ = *text++;
    return out;
}

static uint8_t *append_hex(uint8_t *out, uint32_t value)
{
    static const char digits[] = "0123456789abcdef";
    for (unsigned int i = 0; i < 8; i++) {
        *out++ = digits[value >> 28];
        value <<= 4;
    }
    return out;
}

static uint16_t make_frame(const uint8_t *src_mac, uint32_t mb_magic, uint32_t mb_info)
{
    uint8_t *ip = frame + ETHERNET_HEADER;
    uint8_t *udp = ip + IPV4_HEADER;
    uint8_t *payload = udp + UDP_HEADER;
    uint8_t *end = append_text(payload, "ATVMB1 ");
    end = append_text(end, checkpoint_id);
    end = append_text(end, " EAX=");
    end = append_hex(end, mb_magic);
    end = append_text(end, " EBX=");
    end = append_hex(end, mb_info);
    *end++ = '\n';

    for (unsigned int i = 0; i < sizeof(dst_mac); i++) {
        frame[i] = dst_mac[i];
        frame[i + 6] = src_mac[i];
    }
    put16(frame + 12, 0x0800);

    ip[0] = 0x45;
    ip[1] = 0;
    put16(ip + 2, end - ip);
    put16(ip + 4, 0);
    put16(ip + 6, 0x4000);
    ip[8] = 64;
    ip[9] = 17;
    put16(ip + 10, 0);
    for (unsigned int i = 0; i < sizeof(src_ip); i++) {
        ip[12 + i] = src_ip[i];
        ip[16 + i] = dst_ip[i];
    }
    uint32_t sum = 0;
    for (unsigned int i = 0; i < IPV4_HEADER; i += 2)
        sum += ((uint16_t)ip[i] << 8) | ip[i + 1];
    sum = (sum & 0xffff) + (sum >> 16);
    sum = (sum & 0xffff) + (sum >> 16);
    put16(ip + 10, ~sum);

    put16(udp, ATV_DST_PORT);
    put16(udp + 2, ATV_DST_PORT);
    put16(udp + 4, end - udp);
    put16(udp + 6, 0); /* An omitted UDP checksum is valid over IPv4. */
    while (end < frame + ETHERNET_MINIMUM)
        *end++ = 0;
    return end - frame;
}

static int wait_clear(uint16_t port, uint8_t mask, unsigned int polls)
{
    while (polls-- != 0)
        if (!(in8(port) & mask))
            return 1;
    return 0;
}

void atv_checkpoint(uint32_t mb_magic, uint32_t mb_info)
{
    uint32_t original_address = in32(PCI_ADDRESS);
    pci_select(0);
    if (in32(PCI_DATA) != 0x813910ecu)
        goto restore_address;

    pci_select(PCI_BAR0);
    uint32_t bar = in32(PCI_DATA);
    uint32_t base = bar & ~3u;
    if ((bar & 3) != PCI_IO || base == 0 || base > 0xff00)
        goto restore_address;
#ifdef ATV_EXPECTED_IO
    if (base != ATV_EXPECTED_IO)
        goto restore_address;
#endif
    uint16_t io = base;

    pci_select(PCI_COMMAND);
    uint16_t original_command = in16(PCI_DATA);
    uint16_t command_without_dma = (original_command | PCI_IO) & ~PCI_MASTER;
    pci_write_command(command_without_dma);
    if ((in16(PCI_DATA) & (PCI_IO | PCI_MASTER)) != PCI_IO)
        goto restore_command;

    /* Match the Linux probe's clock wakeup, including after an interface down. */
    out8(io + RTL_HLTCLK, 'R');
    if (in32(io + RTL_TCR) == 0xffffffffu)
        goto restore_command;

    /* The preceding Linux session programmed the current station address. */
    uint8_t src_mac[6];
    uint8_t mac_bits = 0;
    for (unsigned int i = 0; i < sizeof(src_mac); i++) {
        src_mac[i] = in8(io + RTL_IDR0 + i);
        mac_bits |= src_mac[i];
    }
    if (mac_bits == 0 || (src_mac[0] & 1))
        goto stop;

    out16(io + RTL_IMR, 0);
    out8(io + RTL_COMMAND, RTL_RESET);
    if (!wait_clear(io + RTL_COMMAND, RTL_RESET, RESET_POLLS))
        goto stop;
    if (!wait_clear(io + RTL_MEDIA_STATUS, RTL_LINK_DOWN, LINK_POLLS))
        goto stop;

    uint16_t size = make_frame(src_mac, mb_magic, mb_info);
    out16(io + RTL_IMR, 0);
    out16(io + RTL_ISR, 0xffff);
    out8(io + RTL_COMMAND, RTL_TX_ENABLE);
    out32(io + RTL_TCR, RTL_TX_IFG96 | RTL_TX_DMA_1024);
    out32(io + RTL_TSAD0, (uint32_t)(uintptr_t)frame);
    pci_write_command(command_without_dma | PCI_MASTER);
    out32(io + RTL_TSD0, RTL_TX_THRESHOLD_256 | size);
    for (unsigned int i = 0; i < TX_POLLS; i++)
        if (in32(io + RTL_TSD0) & (RTL_TX_OK | RTL_TX_ABORTED))
            break;

stop:
    /* Stop DMA before removing the descriptor or resuming NetBSD startup. */
    pci_write_command(command_without_dma);
    out8(io + RTL_COMMAND, 0);
    if (wait_clear(io + RTL_COMMAND, RTL_RESET | RTL_RX_ENABLE | RTL_TX_ENABLE,
        RESET_POLLS)) {
        out16(io + RTL_IMR, 0);
        out16(io + RTL_ISR, 0xffff);
        out32(io + RTL_TSAD0, 0);
    } else {
        /* Keep bus mastering off if the chip fails to quiesce. */
        original_command &= ~PCI_MASTER;
    }
restore_command:
    pci_write_command(original_command);
restore_address:
    out32(PCI_ADDRESS, original_address);
}
