const { enableAndroidDevSupport } = require('../plugins/with-android-dev-support');

const mainApplication = `class MainApplication {
  override val reactHost: ReactHost by lazy {
    ExpoReactHostFactory.getDefaultReactHost(
      context = applicationContext,
      packageList =
        PackageList(this).packages.apply {
        }
    )
  }
}`;

describe('withAndroidDevSupport', () => {
  it('sets developer support from the app build type and is idempotent', () => {
    const updated = enableAndroidDevSupport(mainApplication);

    expect(updated).toContain('useDevSupport = BuildConfig.DEBUG');
    expect(enableAndroidDevSupport(updated)).toBe(updated);
  });

  it('fails when Expo changes the MainApplication template', () => {
    expect(() => enableAndroidDevSupport('class MainApplication {}')).toThrow(
      'Expected exactly one ExpoReactHostFactory.getDefaultReactHost call in MainApplication.kt'
    );
  });
});
