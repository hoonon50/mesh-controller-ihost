# GitHub, Docker build a nasazení v7.0.2

## Repozitář

Projekt je připravený pro GitHub a používá `.github/workflows/`.

Produkční snapshot v7.0.2 odpovídá commitu:

```text
e3fe1272b7f48e9fa961d57d5f95ac58c52068eb
```

## Produkční build

Workflow:

```text
.github/workflows/build-ihost.yml
```

provádí:

1. checkout repozitáře,
2. QEMU setup,
3. Docker Buildx,
4. login do GHCR,
5. build `linux/arm/v7`,
6. push image do `ghcr.io/hoonon50/mesh-controller-ihost`.

## Dockerfile

`Dockerfile` používá Debian bookworm-slim a instaluje Python, Flask, Paramiko, Gunicorn, tzdata a CA certifikáty.

Po `COPY . .` aplikuje patch chain a následně provádí Python compile a Jinja2 template kontrolu.

To znamená, že finální runtime není prostá kopie jednotlivých základních `.py` souborů. Při lokální validaci vždy stavte image přes Dockerfile.

## Lokální build

```sh
docker build -t mesh-controller-ihost:v7.0.2 .
```

Na x86 hostu pro přesné ARMv7 testování použijte Buildx/QEMU:

```sh
docker buildx build \
  --platform linux/arm/v7 \
  -t mesh-controller-ihost:v7.0.2 \
  --load .
```

## Docker Compose

```sh
docker compose build
docker compose up -d
```

`docker-compose.yml` zachovává:

```text
network_mode: host
mesh-controller-data:/data
restart: unless-stopped
```

## Nasazení na iHost

Při výměně image:

1. nestírejte `mesh-controller-data`,
2. použijte host network,
3. spusťte nový image,
4. ověřte web na portu 8088,
5. zkontrolujte verzi v headeru,
6. ověřte live topologii a přístup na routery.

## GitHub-ready import tohoto ZIPu

Obsah kompletního dokumentačního ZIPu lze použít jako nový repozitář:

```sh
unzip OpenWRT-MESH-CONTROLLER-PRO-v7.0.2_COMPLETE.zip
cd OpenWRT-MESH-CONTROLLER-PRO-v7.0.2
git init
git add .
git commit -m "OpenWRT MESH CONTROLLER PRO v7.0.2"
git branch -M main
git remote add origin <URL_NOVEHO_REPO>
git push -u origin main
```

Před veřejným pushnutím zkontrolujte, že v projektu není vložen reálný `/data/config.json`, heslo nebo jiný secret. Zdrojový repozitář obsahuje pouze `config.example.json` se zástupnou hodnotou `CHANGE_ME`.

## Verze/tagy ve snapshotu

Přesný produkční snapshot v7.0.2 má historickou zvláštnost:

- build workflow stále obsahuje pevný pomocný tag `7.0.1`,
- `docker-compose.yml` stále pojmenovává lokální image `mesh-controller-ihost:7.0.1`,
- `latest` je současně publikovaný produkční tag,
- v7.0.2 aplikační verzi a backup logiku generuje poslední patch v Docker build řetězci.

Tato dokumentace zdrojový stav nemění, aby archiv byl věrným snapshotem projektu. Pokud budete později čistit verzovací infrastrukturu, je vhodné sjednotit pevné tagy v samostatné změně a znovu provést ARMv7 validační build.

## CI doporučení

Před vydáním další verze zachovat minimálně:

- ARMv7 build,
- `py_compile`,
- Jinja template validaci,
- smoke start kontejneru,
- kontrolu jediného OWUT scheduler ownera,
- test Controller backupu/restore manifestu,
- při změnách Nextcloud logiky test retence.