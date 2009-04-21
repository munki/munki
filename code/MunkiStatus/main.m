extern void ASKInitialize();
extern int NSApplicationMain(int argc, const char *argv[]);

int main(int argc, const char *argv[])
{
    ASKInitialize();

    return NSApplicationMain(argc, argv);
}
